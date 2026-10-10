"""Article processing pipeline orchestrating extraction, deterministic pre-filtering, ranking, and Qwen classification."""

from typing import Any, Dict, List, Optional, Tuple
import time

from app.core.config import settings
from app.core.logging import setup_logger
from app.extraction.cleaner import truncate_for_classification
from app.extraction.extractor import ContentExtractor
from app.extraction.fetcher import WebPageFetcher
from app.extraction.models import ExtractedContent
from app.ingestion.models import Article
from app.llm.base import LLMProvider, LLMError
from app.llm.qwen import QwenProvider
from app.processing.filtering import filter_and_deduplicate
from app.processing.models import (
    ALLOWED_TOPICS,
    AIRelevanceClassification,
    RelevanceClassification,
    ProcessedArticle,
    PipelineMetrics,
)
from app.processing.pre_filter import DeterministicPreFilter, PreFilterResult
from app.clustering.clusterer import StoryClusterer
from app.clustering.models import ClusteringMetrics, StoryCluster

logger = setup_logger("article_processor")

TAXONOMY_STRING = ", ".join(ALLOWED_TOPICS)

COMPACT_AI_CLASSIFICATION_PROMPT_TEMPLATE = """Classify if this article is genuinely about Artificial Intelligence (including LLMs, AI agents, machine learning, AI models, NLP/speech, computer vision, AI safety/policy, AI chips/hardware, and AI research).

Return ONLY valid JSON matching this schema:
{{
  "is_relevant": true,
  "relevance_score": 0.95,
  "topic": "AI Agents",
  "reason": "Short explanation under 20 words."
}}

Allowed topics (select EXACTLY one):
AI Agents, LLMs, Generative AI, AI Safety, Machine Learning, Computer Vision, NLP, Robotics, AI Infrastructure, AI Hardware, AI Research, AI Startups, Other.
(Speech/audio -> NLP, policy/ethics -> AI Safety, chips/power -> AI Hardware/Infrastructure)

Title: {title}
Source: {source}
Description: {description}
Article Excerpt:
{content}
"""


class ArticleProcessor:
    """Processes candidate articles through content extraction, pre-filtering, ranking, and LLM classification."""

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        web_fetcher: Optional[WebPageFetcher] = None,
        extractor: Optional[ContentExtractor] = None,
        pre_filter: Optional[DeterministicPreFilter] = None,
        clusterer: Optional[StoryClusterer] = None,
        storage_service: Optional[Any] = None,
    ):
        """Initializes the processor with modular components.

        Args:
            llm_provider: LLM Provider instance (defaults to QwenProvider).
            web_fetcher: WebPageFetcher instance for HTML fetching.
            extractor: ContentExtractor for DOM body extraction.
            pre_filter: DeterministicPreFilter for cheap signal scoring.
            clusterer: StoryClusterer for semantic deduplication and clustering.
            storage_service: StorageService for SQLite persistence and cross-run deduplication.
        """
        self.llm_provider = llm_provider or QwenProvider()
        self.web_fetcher = web_fetcher or WebPageFetcher()
        self.extractor = extractor or ContentExtractor()
        self.pre_filter = pre_filter or DeterministicPreFilter()
        self.clusterer = clusterer or StoryClusterer()
        self.storage_service = storage_service
        self.last_metrics: Optional[PipelineMetrics] = None

    def extract_article_content(self, article: Article) -> ExtractedContent:
        """Fetches webpage HTML and extracts cleaned article prose.

        Args:
            article: Ingested article metadata.

        Returns:
            ExtractedContent: Cleaned prose or fallback text.
        """
        html_str, err = self.web_fetcher.fetch_html(article.url)
        return self.extractor.extract_from_html(
            html_str=html_str or "",
            url=article.url,
            fallback_text=article.description,
        )

    def evaluate_pre_filter(
        self,
        article: Article,
        content: Optional[ExtractedContent] = None,
    ) -> PreFilterResult:
        """Evaluates article through the cheap deterministic pre-filter.

        Args:
            article: Article metadata.
            content: Extracted content if available.

        Returns:
            PreFilterResult: Decision on whether to pass to LLM.
        """
        return self.pre_filter.evaluate(article, content)

    def build_prompt(
        self,
        article: Article,
        content: Optional[ExtractedContent] = None,
    ) -> str:
        """Formats the classification prompt incorporating metadata and compact excerpt.

        Optimized for CPU inference: caps excerpt to ~350 characters to keep prompt tokens low.

        Args:
            article: Candidate article.
            content: Extracted content instance.

        Returns:
            str: Compact populated prompt string.
        """
        desc = article.description or "No description provided."
        if len(desc) > 200:
            desc = desc[:200] + "..."

        body_text = (
            content.text
            if content and content.extraction_success
            else (article.description or "")
        )
        truncated_body = truncate_for_classification(body_text, max_chars=350)
        if not truncated_body:
            truncated_body = "None."

        from app.domains.registry import get_domain_registry
        reg = get_domain_registry()
        dom_key = reg.normalize_domain_key(article.domain or "ai")
        template = reg.get_prompt_template(dom_key)
        allowed_topics = reg.get_allowed_topics(dom_key)
        topics_str = ", ".join(allowed_topics)

        try:
            return template.format(
                topics=topics_str,
                taxonomy=topics_str,
                title=article.title,
                source=article.source,
                description=desc,
                content=truncated_body,
            )
        except Exception:
            return COMPACT_AI_CLASSIFICATION_PROMPT_TEMPLATE.format(
                title=article.title,
                source=article.source,
                description=desc,
                content=truncated_body,
            )

    def classify_article(
        self,
        article: Article,
        content: Optional[ExtractedContent] = None,
        pre_filter_result: Optional[PreFilterResult] = None,
        ranking_score: float = 0.0,
    ) -> ProcessedArticle:
        """Classifies a single article using the LLM provider.

        Args:
            article: Article to evaluate.
            content: Optional pre-extracted content.
            pre_filter_result: Optional pre-computed pre-filter result.
            ranking_score: Optional candidate ranking score.

        Returns:
            ProcessedArticle: Article paired with its validated classification.

        Raises:
            LLMError: If LLM invocation or parsing fails.
        """
        prompt = self.build_prompt(article, content)
        classification = self.llm_provider.generate_structured(
            prompt=prompt,
            schema=RelevanceClassification,
            temperature=0.0,
            max_tokens=128,
        )
        if hasattr(classification, "domain"):
            classification.domain = article.domain
        return ProcessedArticle(
            article=article,
            classification=classification,
            extracted_content=content,
            pre_filter=pre_filter_result,
            ranking_score=ranking_score,
        )

    def classify_article_deterministic(
        self,
        article: Article,
        content: Optional[ExtractedContent] = None,
        pre_filter_result: Optional[PreFilterResult] = None,
        ranking_score: Optional[float] = None,
    ) -> ProcessedArticle:
        """Performs fast deterministic, source-grounded classification without any LLM calls.

        Uses domain registry keyword taxonomy for subtopic matching and extracts
        source-grounded summaries from lead sentences or clean article excerpts.
        """
        from app.domains.registry import get_domain_registry

        reg = get_domain_registry()
        domain_key = reg.normalize_domain_key(article.domain or "ai")
        allowed_topics = reg.get_allowed_topics(domain_key)

        # 1. Deterministic topic selection via keyword matching
        text_corpus = f"{article.title} {article.description or ''}".lower()
        matched_topic = "General"
        for top in allowed_topics:
            if top.lower() != "other" and top.lower() in text_corpus:
                matched_topic = top
                break
        if matched_topic == "General" and allowed_topics:
            matched_topic = allowed_topics[0]

        # 2. Source-grounded concise summary (robust lead sentences or description)
        summary = ""
        raw_text = ""
        if content and content.text and len(content.text.strip()) > 30:
            raw_text = content.text.strip()
        elif article.description and len(article.description.strip()) > 20:
            raw_text = article.description.strip()
        else:
            raw_text = f"{article.title} reported by {article.source}."

        import re
        # Split on sentence boundaries: period/question/exclamation followed by space and uppercase letter or end
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+(?=[A-Z0-9])', raw_text) if len(s.strip()) > 10]
        if sentences:
            summary = " ".join(sentences[:2])
        else:
            summary = raw_text

        # Guarantee minimum 15 characters for valid publication
        if len(summary.strip()) < 15:
            if len(raw_text) >= 15:
                summary = raw_text[:250].strip()
            else:
                summary = f"{article.title} reported by {article.source}."

        if len(summary) > 295:
            summary = summary[:292] + "..."

        score = ranking_score if ranking_score is not None else (
            pre_filter_result.ranking_score if pre_filter_result else 0.85
        )

        classification = RelevanceClassification(
            is_relevant=True,
            relevance_score=min(1.0, max(0.60, score)),
            topic=matched_topic,
            reason=summary,
            domain=article.domain,
        )

        return ProcessedArticle(
            article=article,
            classification=classification,
            extracted_content=content,
            pre_filter=pre_filter_result,
            ranking_score=score,
        )

    def process_with_metrics(
        self,
        articles: List[Article],
        max_candidates: Optional[int] = None,
        enable_extraction: bool = True,
        enable_pre_filter: bool = True,
        enable_clustering: bool = True,
        enable_storage: Optional[bool] = None,
        enable_agentic_workflow: bool = False,
        enable_llm_inference: Optional[bool] = None,
    ) -> Tuple[List[ProcessedArticle], PipelineMetrics]:
        """Runs the pipeline and returns processed articles with detailed metrics.

        Pipeline steps:
        1. Basic deterministic filtering & in-memory URL deduplication.
        1.5. Persistent storage deduplication (skips previously classified/rejected articles).
        2. Article content extraction.
        3. Cheap deterministic pre-filtering (categorizes into HIGH/MEDIUM/LOW).
        4. Candidate ranking by priority score.
        5. Semantic story clustering & cross-day story matching against historical events (Phases 4 & 5).
        6. Top-K selection (prioritizing strongest AI candidates).
        7. Fast sequential Qwen relevance classification.
        8. Atomic persistence of classification results and cluster associations.

        Args:
            articles: Ingested raw articles.
            max_candidates: Maximum articles to send to Qwen (default from settings).
            enable_extraction: Whether to fetch full article webpages.
            enable_pre_filter: Whether to apply deterministic pre-filtering.
            enable_clustering: Whether to cluster candidate stories before LLM inference.
            enable_storage: Whether to query and write to SQLite persistent storage.

        Returns:
            Tuple[List[ProcessedArticle], PipelineMetrics]: Results and metrics.
        """
        pipeline_start = time.time()
        metrics = PipelineMetrics(
            total_rss_articles=len(articles),
            articles_collected=len(articles),
        )
        for a in articles:
            dom = a.domain or "AI"
            metrics.domain_counts[dom] = metrics.domain_counts.get(dom, 0) + 1

        if enable_storage is True:
            if self.storage_service is None:
                from app.storage.service import StorageService
                self.storage_service = StorageService()
            use_storage = True
        elif enable_storage is False:
            use_storage = False
        else:
            use_storage = self.storage_service is not None

        # Step 1: Basic validation & deduplication
        filtered = filter_and_deduplicate(articles)
        metrics.valid_articles = len(filtered)

        # Step 1.5: Persistent storage lookup & cross-run deduplication
        working_articles = filtered
        if use_storage and self.storage_service:
            to_process, skipped, s_metrics = self.storage_service.check_and_register_articles(filtered)
            metrics.new_articles_persisted = s_metrics.new_articles_persisted
            metrics.exact_duplicates_skipped = s_metrics.exact_duplicates_skipped
            metrics.previously_seen_articles_recognized = s_metrics.previously_seen_recognized
            metrics.qwen_evaluations_avoided += len(skipped)
            metrics.storage_failures = s_metrics.storage_failures
            working_articles = to_process

            if not working_articles:
                logger.info(
                    f"All {len(filtered)} ingested articles were previously processed or skipped. "
                    f"Avoided all LLM evaluations."
                )
                metrics.total_runtime_seconds = round(time.time() - pipeline_start, 2)
                self.last_metrics = metrics
                return [], metrics

        # Determine LLM inference requirement
        use_llm = (
            enable_llm_inference
            if enable_llm_inference is not None
            else (not getattr(settings, "cpu_only_mode", False) and getattr(settings, "enable_llm_inference", True))
        )

        # Step 2 & 3: Fast Pre-filtering and Targeted Extraction
        extracted_map: dict[str, ExtractedContent] = {}
        candidate_pairs: List[Tuple[Article, PreFilterResult]] = []
        rejected_articles: List[Article] = []

        for article in working_articles:
            # Deterministic Pre-filter evaluated quickly on title + description
            if enable_pre_filter:
                pf = self.evaluate_pre_filter(article, None)
                if not pf.should_send_to_llm:
                    rejected_articles.append(article)
                    metrics.rejected_pre_filter += 1
                    continue
            else:
                pf = PreFilterResult(
                    pre_filter_score=1.0,
                    tier="HIGH",
                    ranking_score=1.0,
                    should_send_to_llm=True,
                    reason="Pre-filtering disabled",
                )

            # Targeted Extraction: In CPU-only mode, use substantive feed descriptions
            # to avoid blocking on hundreds of sequential HTTP roundtrips.
            needs_dom_extraction = enable_extraction and (
                use_llm or not article.description or len(article.description.strip()) < 30
            )

            if needs_dom_extraction:
                ext = self.extract_article_content(article)
                extracted_map[article.url] = ext
                if ext.extraction_success:
                    metrics.extraction_success += 1
                else:
                    metrics.extraction_failed += 1
            else:
                ext = ExtractedContent(
                    url=article.url,
                    text=article.description or "",
                    word_count=len((article.description or "").split()),
                    extraction_method="rss_fallback",
                    extraction_success=True,
                )
                extracted_map[article.url] = ext
                metrics.extraction_success += 1

            candidate_pairs.append((article, pf))

        if use_storage and self.storage_service and rejected_articles:
            self.storage_service.mark_articles_prefilter_rejected(rejected_articles)

        metrics.candidates_passed_to_llm = len(candidate_pairs)
        metrics.qwen_calls_saved = metrics.valid_articles - len(candidate_pairs)
        if metrics.valid_articles > 0:
            metrics.reduction_percentage = round(
                (metrics.qwen_calls_saved / metrics.valid_articles) * 100.0, 1
            )

        # Step 4: Deterministic Candidate Ranking
        ranked_pairs = self.pre_filter.rank_candidates(candidate_pairs)

        # Step 5: Semantic Clustering & Cross-Day Deduplication (Phases 4 & 5)
        cluster_map: Dict[str, StoryCluster] = {}
        target_candidates: List[Tuple[Article, PreFilterResult, Optional[StoryCluster]]] = []
        processed_list: List[ProcessedArticle] = []

        if enable_clustering and ranked_pairs:
            candidate_articles = [art for art, _ in ranked_pairs]
            unmerged_candidates = candidate_articles
            historical_matches: Dict[str, Tuple[str, bool, str]] = {}

            # Cross-day story matching against persisted historical clusters
            if use_storage and self.storage_service:
                hist_candidates = self.storage_service.get_historical_cluster_candidates()
                if hist_candidates:
                    historical_matches, unmerged_candidates = self.clusterer.match_historical_stories(
                        candidate_articles=candidate_articles,
                        historical_candidates=hist_candidates,
                        extracted_map=extracted_map,
                    )
                    metrics.historical_story_matches = len(historical_matches)

                    seen_hist_clusters: set = set()
                    for cand_url, (hist_cl_id, is_meaningful, update_reason) in historical_matches.items():
                        cand_art = next(a for a in candidate_articles if a.url == cand_url)
                        if is_meaningful:
                            metrics.meaningful_story_updates_detected += 1

                        # Reuse historical cluster taxonomy and relevance only for meaningful updates
                        if is_meaningful:
                            seen_hist_clusters.add(hist_cl_id)
                            hist_rec = self.storage_service.db.get_cluster_by_id(hist_cl_id)
                            hist_rep_rec = (
                                self.storage_service.db.get_article_by_id(hist_rec.representative_article_id)
                                if hist_rec
                                else None
                            )
                            topic = (hist_rep_rec.topic if hist_rep_rec else None) or "Other"
                            rel_score = (hist_rep_rec.relevance_score if hist_rep_rec else None) or 0.90

                            cand_ext = extracted_map.get(cand_art.url)
                            cand_pf = next((pf for a, pf in candidate_pairs if a.url == cand_art.url), None)

                            all_sources = list(
                                set((hist_rec.sources if hist_rec else []) + [cand_art.source])
                            )
                            reason_text = f"Meaningful update: {update_reason}"
                            if not reason_text or len(reason_text.strip()) < 15:
                                reason_text = f"{cand_art.title} reported by {cand_art.source}."
                            if len(reason_text) > 295:
                                reason_text = reason_text[:292] + "..."

                            update_processed = ProcessedArticle(
                                article=cand_art,
                                classification=RelevanceClassification(
                                    is_relevant=True,
                                    relevance_score=rel_score,
                                    topic=topic,
                                    reason=reason_text,
                                    domain=cand_art.domain,
                                ),
                                extracted_content=cand_ext,
                                pre_filter=cand_pf,
                                ranking_score=cand_pf.ranking_score if cand_pf else 1.0,
                                cluster_id=hist_cl_id,
                                cluster_source_count=len(all_sources),
                                cluster_sources=all_sources,
                            )
                            processed_list.append(update_processed)
                            self.storage_service.persist_processed_article(update_processed)

                        metrics.qwen_evaluations_avoided += 1

                        hist_cluster_obj = StoryCluster(
                            cluster_id=hist_cl_id,
                            representative_article=cand_art,
                            member_articles=[cand_art],
                            source_count=1,
                            sources=[cand_art.source],
                        )
                        self.storage_service.persist_cluster_group(
                            hist_cluster_obj,
                            is_update=True,
                            meaningful_update=is_meaningful,
                            update_reason=update_reason,
                        )

            # Form new clusters on unmerged candidate articles
            if unmerged_candidates:
                clusters, c_metrics = self.clusterer.cluster_articles(
                    articles=unmerged_candidates,
                    extracted_map=extracted_map,
                )
                metrics.total_clusters = c_metrics.total_clusters + len(historical_matches)
                metrics.new_story_clusters_created = c_metrics.total_clusters
                metrics.multi_source_clusters = c_metrics.multi_source_clusters
                metrics.clustering_saved_calls = c_metrics.total_input_articles - c_metrics.total_clusters
                metrics.clustering_runtime_seconds = c_metrics.clustering_runtime_seconds

                if use_storage and self.storage_service:
                    for c in clusters:
                        self.storage_service.persist_cluster_group(c)

                for c in clusters:
                    cluster_map[c.representative_article.url] = c

                # Select only cluster representatives, preserving rank order
                seen_rep_urls = set()
                for art, pf in ranked_pairs:
                    if art.url in cluster_map and art.url not in seen_rep_urls:
                        target_candidates.append((art, pf, cluster_map[art.url]))
                        seen_rep_urls.add(art.url)
            else:
                metrics.total_clusters = len(historical_matches)
                metrics.new_story_clusters_created = 0
        else:
            target_candidates = [(art, pf, None) for art, pf in ranked_pairs]

        # Step 6: Candidate Selection (Top-K for LLM, full cluster representation for CPU-only)
        k_limit = (
            max_candidates
            if max_candidates is not None
            else (settings.qwen_max_candidates if use_llm else 0)
        )
        candidates_to_classify = (
            target_candidates[:k_limit] if k_limit > 0 else target_candidates
        )

        logger.info(
            f"Pre-filter retained {len(candidate_pairs)}/{len(working_articles)} candidates "
            f"({metrics.reduction_percentage}% reduction). "
            f"Clustering formed {metrics.total_clusters} story clusters "
            f"({metrics.multi_source_clusters} multi-source, {metrics.historical_story_matches} historical matches). "
            f"Selected {len(candidates_to_classify)} candidate stories for classification (use_llm={use_llm})."
        )

        # Step 7: Classification (either via LangGraph Agentic Intelligence, Direct Qwen, or Deterministic CPU-Only)
        qwen_start = time.time()

        if not use_llm:
            logger.info("Deterministic CPU-only mode: generating source-grounded summaries without LLM inference.")
            for idx, (article, pf, cluster_obj) in enumerate(candidates_to_classify, start=1):
                ext = extracted_map.get(article.url)
                processed = self.classify_article_deterministic(
                    article=article,
                    content=ext,
                    pre_filter_result=pf,
                    ranking_score=pf.ranking_score,
                )
                if cluster_obj:
                    processed.cluster_id = cluster_obj.cluster_id
                    processed.cluster_source_count = cluster_obj.source_count
                    processed.cluster_sources = cluster_obj.sources

                processed_list.append(processed)
                if use_storage and self.storage_service:
                    self.storage_service.persist_processed_article(processed)

                metrics.qwen_relevant += 1

            metrics.qwen_calls = 0
            metrics.qwen_calls_saved += len(candidates_to_classify)
        elif enable_agentic_workflow and candidates_to_classify:
            from app.intelligence.models import CandidateStoryInput
            from app.intelligence.workflow import IntelligenceWorkflow

            import hashlib
            candidate_inputs: List[CandidateStoryInput] = []
            for article, pf, cluster_obj in candidates_to_classify:
                c_id = (
                    cluster_obj.cluster_id
                    if cluster_obj
                    else f"cluster_{hashlib.sha256(article.url.encode()).hexdigest()[:12]}"
                )
                c_sources = cluster_obj.sources if cluster_obj else [article.source]
                c_members = cluster_obj.member_articles if cluster_obj else [article]
                candidate_inputs.append(
                    CandidateStoryInput(
                        cluster_id=c_id,
                        representative_article=article,
                        member_articles=c_members,
                        extracted_content=extracted_map.get(article.url),
                        pre_filter_result=pf,
                        ranking_score=pf.ranking_score,
                        domain=article.domain or "ai",
                        sources=c_sources,
                    )
                )

            graph_workflow = IntelligenceWorkflow(llm_provider=self.llm_provider)
            graph_state = graph_workflow.run(candidate_inputs)

            for synth_story in graph_state.get("synthesized_stories", {}).values():
                orig_item = next(
                    (cand for cand in candidate_inputs if cand.cluster_id == synth_story.cluster_id),
                    None,
                )
                if not orig_item:
                    continue

                processed = ProcessedArticle(
                    article=orig_item.representative_article,
                    classification=RelevanceClassification(
                        is_relevant=True,
                        relevance_score=synth_story.relevance_score,
                        topic=synth_story.topic,
                        reason=synth_story.summary,
                        domain=synth_story.domain,
                    ),
                    extracted_content=orig_item.extracted_content,
                    pre_filter=orig_item.pre_filter_result,
                    ranking_score=synth_story.priority_score,
                    cluster_id=synth_story.cluster_id,
                    cluster_source_count=synth_story.source_count,
                    cluster_sources=synth_story.sources,
                )
                processed_list.append(processed)
                if use_storage and self.storage_service:
                    self.storage_service.persist_processed_article(processed)

            metrics.qwen_calls += graph_state.get("llm_call_count", len(candidate_inputs))
            metrics.qwen_relevant += len(processed_list)
        else:
            for idx, (article, pf, cluster_obj) in enumerate(candidates_to_classify, start=1):
                logger.info(
                    f"[{idx}/{len(candidates_to_classify)}] Classifying (rank={pf.ranking_score:.3f}, tier={pf.tier}): "
                    f"'{article.title[:55]}...'"
                )
                ext = extracted_map.get(article.url)
                try:
                    processed = self.classify_article(
                        article=article,
                        content=ext,
                        pre_filter_result=pf,
                        ranking_score=pf.ranking_score,
                    )
                    if cluster_obj:
                        processed.cluster_id = cluster_obj.cluster_id
                        processed.cluster_source_count = cluster_obj.source_count
                        processed.cluster_sources = cluster_obj.sources

                    processed_list.append(processed)
                    if use_storage and self.storage_service:
                        self.storage_service.persist_processed_article(processed)

                    metrics.qwen_calls += 1
                    if processed.classification.is_relevant:
                        metrics.qwen_relevant += 1
                    else:
                        metrics.qwen_irrelevant += 1
                except LLMError as err:
                    logger.warning(
                        f"LLM unavailable for '{article.title}': {err}. "
                        f"Falling back to deterministic source-grounded summary."
                    )
                    processed = self.classify_article_deterministic(
                        article=article,
                        content=ext,
                        pre_filter_result=pf,
                        ranking_score=pf.ranking_score,
                    )
                    if cluster_obj:
                        processed.cluster_id = cluster_obj.cluster_id
                        processed.cluster_source_count = cluster_obj.source_count
                        processed.cluster_sources = cluster_obj.sources

                    processed_list.append(processed)
                    if use_storage and self.storage_service:
                        self.storage_service.persist_processed_article(processed)
                    metrics.qwen_relevant += 1
                except Exception as err:
                    logger.error(f"Unexpected error classifying '{article.title}': {err}. Skipping.")
                    if use_storage and self.storage_service:
                        self.storage_service.mark_article_failed(article, str(err))

        metrics.qwen_runtime_seconds = round(time.time() - qwen_start, 2)
        if metrics.qwen_calls > 0:
            metrics.average_qwen_seconds = round(
                metrics.qwen_runtime_seconds / metrics.qwen_calls, 2
            )

        metrics.total_runtime_seconds = round(time.time() - pipeline_start, 2)
        self.last_metrics = metrics
        return processed_list, metrics

    def cluster_articles(
        self,
        articles: List[Article],
        extracted_map: Optional[Dict[str, ExtractedContent]] = None,
    ) -> Tuple[List[StoryCluster], ClusteringMetrics]:
        """Direct access to semantic clustering of articles."""
        return self.clusterer.cluster_articles(articles, extracted_map)

    def process_articles(
        self,
        articles: List[Article],
        max_candidates: Optional[int] = None,
    ) -> List[ProcessedArticle]:
        """Backward-compatible entry point returning processed articles."""
        results, _ = self.process_with_metrics(
            articles=articles,
            max_candidates=max_candidates,
            enable_extraction=True,
            enable_pre_filter=True,
        )
        return results
