"""Core story clustering and semantic deduplication engine."""

import hashlib
import time
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from app.clustering.embeddings import EmbeddingProvider, get_embedding_provider
from app.clustering.entity_guard import EntityGuard
from app.clustering.models import ClusteringMetrics, StoryCluster
from app.clustering.representative import RepresentativeSelector
from app.core.config import settings
from app.core.logging import setup_logger
from app.extraction.models import ExtractedContent
from app.ingestion.models import Article

logger = setup_logger("clusterer")


class StoryClusterer:
    """Clusters articles covering the same real-world event into unified StoryCluster instances."""

    def __init__(
        self,
        embedding_provider: Optional[EmbeddingProvider] = None,
        entity_guard: Optional[EntityGuard] = None,
        similarity_threshold: Optional[float] = None,
        time_window_hours: Optional[float] = None,
    ):
        """Initializes clusterer with embedding, guardrails, and thresholds.

        Args:
            embedding_provider: EmbeddingProvider instance (defaults to TFIDFEmbeddingProvider).
            entity_guard: EntityGuard instance for merge safety.
            similarity_threshold: Minimum cosine similarity to merge articles (default from settings).
            time_window_hours: Maximum allowable publication time difference.
        """
        self.embedding_provider = embedding_provider or get_embedding_provider(
            settings.clustering_embedding_provider
        )
        time_win = (
            time_window_hours
            if time_window_hours is not None
            else settings.clustering_time_window_hours
        )
        self.entity_guard = entity_guard or EntityGuard(time_window_hours=time_win)
        self.similarity_threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else settings.clustering_similarity_threshold
        )
        self.representative_selector = RepresentativeSelector()

    def build_article_text(self, article: Article) -> str:
        """Constructs weighted text representation emphasizing title while incorporating summary."""
        # Repeat title twice to grant higher weight to specific headline terminology
        title_part = f"{article.title} {article.title}"
        desc_part = (article.description or "").strip()
        return f"{title_part} {desc_part}".strip()

    def cluster_articles(
        self,
        articles: List[Article],
        extracted_map: Optional[Dict[str, ExtractedContent]] = None,
    ) -> Tuple[List[StoryCluster], ClusteringMetrics]:
        """Clusters candidate articles into story groups with deterministic representative selection.

        Args:
            articles: List of ingested articles to cluster.
            extracted_map: Optional dictionary mapping article URLs to ExtractedContent.

        Returns:
            Tuple[List[StoryCluster], ClusteringMetrics]: Formed clusters and execution metrics.
        """
        start_time = time.time()
        metrics = ClusteringMetrics(total_input_articles=len(articles))

        if not articles:
            metrics.clustering_runtime_seconds = round(time.time() - start_time, 4)
            return [], metrics

        extracted_map = extracted_map or {}

        # Step 1: Pre-group exact duplicate URLs and identical normalized titles
        exact_groups: List[List[Article]] = []
        seen_keys: Dict[str, int] = {}  # key -> group index

        for art in articles:
            url_key = art.url.strip().lower()
            title_key = art.title.strip().lower()

            if url_key in seen_keys:
                exact_groups[seen_keys[url_key]].append(art)
            elif title_key in seen_keys:
                exact_groups[seen_keys[title_key]].append(art)
            else:
                idx = len(exact_groups)
                exact_groups.append([art])
                seen_keys[url_key] = idx
                seen_keys[title_key] = idx

        # If only 1 group existed, build single cluster directly
        if len(exact_groups) == 1:
            cluster = self._build_cluster(exact_groups[0], extracted_map, 1.0)
            metrics.total_clusters = 1
            if cluster.source_count > 1:
                metrics.multi_source_clusters = 1
            else:
                metrics.single_article_clusters = 1
            metrics.deduplication_ratio = round(
                (1.0 - (1.0 / len(articles))) * 100.0, 1
            ) if len(articles) > 1 else 0.0
            metrics.clustering_runtime_seconds = round(time.time() - start_time, 4)
            return [cluster], metrics

        # Step 2: Semantic embedding and pairwise comparison across group representatives
        # Use primary article from each exact group for semantic comparison
        rep_articles = [grp[0] for grp in exact_groups]
        texts = [self.build_article_text(art) for art in rep_articles]

        sim_matrix = self.embedding_provider.compute_similarity_matrix(texts)
        n = len(rep_articles)

        # Step 3: Guardrail-checked cluster formation
        # Each group starts as an independent cluster
        cluster_assignment: List[int] = list(range(n))

        def find(i: int) -> int:
            while cluster_assignment[i] != i:
                cluster_assignment[i] = cluster_assignment[cluster_assignment[i]]
                i = cluster_assignment[i]
            return i

        def union(i: int, j: int):
            root_i = find(i)
            root_j = find(j)
            if root_i != root_j:
                cluster_assignment[root_j] = root_i

        # Evaluate candidate merge edges sorted by composite similarity descending
        candidate_edges: List[Tuple[float, int, int]] = []
        composite_sim_matrix = np.copy(sim_matrix)

        for i in range(n):
            for j in range(i + 1, n):
                allowed, reason = self.entity_guard.is_merge_allowed(
                    rep_articles[i],
                    rep_articles[j],
                    texts[i],
                    texts[j],
                )
                if not allowed:
                    composite_sim_matrix[i, j] = 0.0
                    composite_sim_matrix[j, i] = 0.0
                    continue

                base_score = float(sim_matrix[i, j])
                bonus = self.entity_guard.compute_semantic_bonus(
                    rep_articles[i],
                    rep_articles[j],
                    texts[i],
                    texts[j],
                )
                total_score = min(1.0, base_score + bonus)
                composite_sim_matrix[i, j] = total_score
                composite_sim_matrix[j, i] = total_score

                if total_score >= self.similarity_threshold:
                    candidate_edges.append((total_score, i, j))

        candidate_edges.sort(key=lambda x: x[0], reverse=True)

        # Merge groups if all member pairs satisfy EntityGuard
        for score, i, j in candidate_edges:
            root_i = find(i)
            root_j = find(j)
            if root_i == root_j:
                continue

            # Verify clique compatibility: check that merging cluster_i and cluster_j
            # does not violate guardrails between ANY pair of articles
            members_i = [idx for idx in range(n) if find(idx) == root_i]
            members_j = [idx for idx in range(n) if find(idx) == root_j]

            merge_safe = True
            for m_i in members_i:
                for m_j in members_j:
                    allowed, reason = self.entity_guard.is_merge_allowed(
                        rep_articles[m_i],
                        rep_articles[m_j],
                        texts[m_i],
                        texts[m_j],
                    )
                    if not allowed:
                        logger.debug(
                            f"Prevented merge of '{rep_articles[m_i].title[:40]}' "
                            f"and '{rep_articles[m_j].title[:40]}': {reason}"
                        )
                        merge_safe = False
                        break
                if not merge_safe:
                    break

            if merge_safe:
                union(root_i, root_j)

        # Step 4: Assemble final clusters
        clusters_by_root: Dict[int, List[Article]] = {}
        cluster_sim_scores: Dict[int, List[float]] = {}

        for group_idx, grp in enumerate(exact_groups):
            root = find(group_idx)
            if root not in clusters_by_root:
                clusters_by_root[root] = []
                cluster_sim_scores[root] = []
            clusters_by_root[root].extend(grp)

        # Collect pairwise similarities within multi-article clusters
        for i in range(n):
            for j in range(i + 1, n):
                if find(i) == find(j):
                    cluster_sim_scores[find(i)].append(float(composite_sim_matrix[i, j]))

        formed_clusters: List[StoryCluster] = []
        for root, member_articles in clusters_by_root.items():
            scores = cluster_sim_scores.get(root, [])
            mean_sim = float(np.mean(scores)) if scores else 1.0
            cluster = self._build_cluster(
                member_articles=member_articles,
                extracted_map=extracted_map,
                similarity_score=mean_sim,
            )
            formed_clusters.append(cluster)

        # Sort clusters deterministically: multi-source first, then by representative quality
        formed_clusters.sort(
            key=lambda c: (c.source_count, len(c.member_articles)),
            reverse=True,
        )

        # Populate metrics
        metrics.total_clusters = len(formed_clusters)
        metrics.multi_source_clusters = sum(1 for c in formed_clusters if c.source_count > 1)
        metrics.single_article_clusters = sum(1 for c in formed_clusters if len(c.member_articles) == 1)
        if metrics.total_input_articles > 0:
            reduction = (
                (metrics.total_input_articles - metrics.total_clusters)
                / metrics.total_input_articles
            ) * 100.0
            metrics.deduplication_ratio = round(max(0.0, reduction), 1)

        metrics.clustering_runtime_seconds = round(time.time() - start_time, 4)
        logger.info(
            f"Clustered {len(articles)} articles into {len(formed_clusters)} story clusters "
            f"({metrics.multi_source_clusters} multi-source, "
            f"{metrics.deduplication_ratio}% deduplication ratio) in {metrics.clustering_runtime_seconds}s."
        )
        return formed_clusters, metrics

    def _build_cluster(
        self,
        member_articles: List[Article],
        extracted_map: Dict[str, ExtractedContent],
        similarity_score: float,
    ) -> StoryCluster:
        """Constructs a StoryCluster instance with elected representative and source metadata."""
        representative = self.representative_selector.select_representative(
            articles=member_articles,
            extracted_map=extracted_map,
        )

        # Unique sources
        unique_sources = list({art.source for art in member_articles})
        unique_sources.sort()

        # Deterministic cluster ID from representative URL hash
        hash_digest = hashlib.sha256(representative.url.encode("utf-8")).hexdigest()[:12]
        cluster_id = f"cluster_{hash_digest}"

        # Calculate time span in hours between earliest and latest published member
        valid_timestamps = [
            art.published_at for art in member_articles if art.published_at is not None
        ]
        time_span = 0.0
        if len(valid_timestamps) >= 2:
            earliest = min(valid_timestamps)
            latest = max(valid_timestamps)
            time_span = round(abs((latest - earliest).total_seconds()) / 3600.0, 2)

        return StoryCluster(
            cluster_id=cluster_id,
            representative_article=representative,
            member_articles=member_articles,
            source_count=len(unique_sources),
            sources=unique_sources,
            similarity_score=round(similarity_score, 4),
            time_span_hours=time_span,
        )

    def match_historical_stories(
        self,
        candidate_articles: List[Article],
        historical_candidates: List[Tuple[Any, Article]],
        extracted_map: Optional[Dict[str, ExtractedContent]] = None,
    ) -> Tuple[Dict[str, Tuple[str, bool, str]], List[Article]]:
        """Matches incoming candidate articles against bounded historical story cluster representatives.

        Enforces all EntityGuard checks (model versions, conflicting entities, distinct event types,
        time window). If matched, determines if the article represents a meaningful story update or
        redundant duplicate coverage.

        Args:
            candidate_articles: Newly ingested candidate articles.
            historical_candidates: List of tuples (cluster_record_or_id, representative_article).
            extracted_map: Optional dictionary of ExtractedContent.

        Returns:
            Tuple[Dict[str, Tuple[str, bool, str]], List[Article]]:
                - matches: mapping article.url -> (cluster_id, is_meaningful_update, update_reason)
                - unmerged: articles that did not match any historical story and must form new clusters.
        """
        from app.storage.fingerprint import is_meaningful_update

        extracted_map = extracted_map or {}
        matches: Dict[str, Tuple[str, bool, str]] = {}
        unmerged: List[Article] = []

        if not historical_candidates:
            return {}, list(candidate_articles)

        from sklearn.metrics.pairwise import cosine_similarity

        cand_texts = [self.build_article_text(cand) for cand in candidate_articles]
        hist_texts = [self.build_article_text(hist_rep) for _, hist_rep in historical_candidates]

        cand_embeddings = self.embedding_provider.embed_texts(cand_texts)
        hist_embeddings = self.embedding_provider.embed_texts(hist_texts)
        sim_matrix = cosine_similarity(cand_embeddings, hist_embeddings)

        for i, cand in enumerate(candidate_articles):
            cand_text = cand_texts[i]
            best_match: Optional[Tuple[str, float, bool, str]] = None  # (cl_id, score, is_meaningful, reason)

            for j, (hist_entry, hist_rep) in enumerate(historical_candidates):
                hist_cl_id = getattr(hist_entry, "id", None) or str(hist_entry)
                hist_text = hist_texts[j]

                # Guardrail check 1: EntityGuard
                allowed, guard_reason = self.entity_guard.is_merge_allowed(
                    cand, hist_rep, cand_text, hist_text
                )
                if not allowed:
                    continue

                # Guardrail check 2: Pairwise semantic similarity (pre-computed batch cosine sim)
                base_sim = float(sim_matrix[i, j]) if sim_matrix.size > 0 else 0.0
                bonus = self.entity_guard.compute_semantic_bonus(
                    cand, hist_rep, cand_text, hist_text
                )
                total_sim = min(1.0, base_sim + bonus)

                if total_sim >= self.similarity_threshold:
                    # Calculate publication time difference
                    t_diff = 0.0
                    if cand.published_at and hist_rep.published_at:
                        t_diff = abs((cand.published_at - hist_rep.published_at).total_seconds()) / 3600.0

                    cand_ext = extracted_map.get(cand.url)
                    cand_body = cand_ext.text if cand_ext else cand.description
                    meaningful, update_reason = is_meaningful_update(
                        old_article=hist_rep,
                        new_article=cand,
                        time_diff_hours=t_diff,
                        old_text=hist_rep.description,
                        new_text=cand_body,
                    )

                    if best_match is None or total_sim > best_match[1]:
                        best_match = (hist_cl_id, total_sim, meaningful, update_reason)

            if best_match is not None:
                cl_id, score, is_meaningful, reason = best_match
                matches[cand.url] = (cl_id, is_meaningful, reason)
                logger.info(
                    f"Matched article '{cand.title[:45]}' to historical cluster '{cl_id}' "
                    f"(sim={score:.3f}, meaningful_update={is_meaningful})"
                )
            else:
                unmerged.append(cand)

        return matches, unmerged
