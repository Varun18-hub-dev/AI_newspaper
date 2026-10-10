"""LangGraph orchestration workflow for multi-domain news intelligence."""

from datetime import datetime
import time
from typing import Any, Dict, List, Optional, Tuple

from langgraph.graph import StateGraph, START, END

from app.core.logging import setup_logger
from app.intelligence.evidence import EvidenceValidator
from app.intelligence.models import (
    CandidateStoryInput,
    EvidenceValidationResult,
    IntelligenceGraphState,
    SpecialistAnalysisResult,
    StorySynthesisResult,
)
from app.intelligence.specialists import get_domain_specialist
from app.llm.base import LLMProvider

logger = setup_logger("intelligence_workflow")


class IntelligenceWorkflow:
    """Orchestrates multi-domain news intelligence using LangGraph StateGraph."""

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        evidence_validator: Optional[EvidenceValidator] = None,
    ):
        self.llm_provider = llm_provider
        self.validator = evidence_validator or EvidenceValidator()
        self.graph = self._build_graph()

    def _build_graph(self):
        """Constructs and compiles the LangGraph StateGraph."""
        builder = StateGraph(IntelligenceGraphState)

        # Add explicit processing nodes
        builder.add_node("route_domains", self._node_route_domains)
        builder.add_node("specialist_analysis", self._node_specialist_analysis)
        builder.add_node("validate_evidence", self._node_validate_evidence)
        builder.add_node("rank_and_synthesize", self._node_rank_and_synthesize)

        # Connect explicit sequential flow
        builder.add_edge(START, "route_domains")
        builder.add_edge("route_domains", "specialist_analysis")
        builder.add_edge("specialist_analysis", "validate_evidence")
        builder.add_edge("validate_evidence", "rank_and_synthesize")
        builder.add_edge("rank_and_synthesize", END)

        return builder.compile()

    # =========================================================================
    # Node 1: Domain Routing
    # =========================================================================
    def _node_route_domains(self, state: IntelligenceGraphState) -> IntelligenceGraphState:
        """Inspects candidate clusters and routes each to the matching domain taxonomy."""
        candidates = state.get("candidate_clusters", [])
        domain_routes: Dict[str, str] = {}

        for cand in candidates:
            # Use explicitly set domain or extract from representative article
            dom = (cand.domain or cand.representative_article.domain or "ai").strip().lower()
            if dom in ("artificial intelligence", "ai"):
                normalized_dom = "ai"
            elif dom in ("tech", "technology"):
                normalized_dom = "technology"
            elif dom in ("science",):
                normalized_dom = "science"
            elif dom in ("cybersecurity", "security", "infosec"):
                normalized_dom = "cybersecurity"
            elif dom in ("business", "startups"):
                normalized_dom = "business"
            else:
                normalized_dom = "ai"  # Fallback

            domain_routes[cand.cluster_id] = normalized_dom

        logger.info(f"[LangGraph:route_domains] Routed {len(domain_routes)} candidate story clusters.")
        return {"domain_routes": domain_routes}

    # =========================================================================
    # Node 2: Specialist Analysis
    # =========================================================================
    def _node_specialist_analysis(self, state: IntelligenceGraphState) -> IntelligenceGraphState:
        """Invokes the assigned domain-specialist agent for each candidate cluster."""
        candidates = state.get("candidate_clusters", [])
        routes = state.get("domain_routes", {})
        existing_results = state.get("specialist_results", {})

        new_results: Dict[str, SpecialistAnalysisResult] = dict(existing_results)
        retry_counts = dict(state.get("retry_counts", {}))
        llm_calls = state.get("llm_call_count", 0)
        fallbacks = state.get("fallback_count", 0)

        for cand in candidates:
            cl_id = cand.cluster_id
            # Duplicate call prevention: skip if already analyzed
            if cl_id in new_results:
                continue

            dom = routes.get(cl_id, "ai")
            specialist = get_domain_specialist(dom, llm_provider=self.llm_provider)

            logger.info(
                f"[LangGraph:specialist_analysis] Invoking {specialist.role_name} for cluster '{cl_id}' ({cand.representative_article.title[:50]}...)"
            )

            result = specialist.analyze_cluster(candidate=cand, llm=self.llm_provider)
            new_results[cl_id] = result
            retry_counts[cl_id] = result.retry_count

            if not result.fallback_used:
                llm_calls += 1
            else:
                fallbacks += 1

        return {
            "specialist_results": new_results,
            "retry_counts": retry_counts,
            "llm_call_count": llm_calls,
            "fallback_count": fallbacks,
        }

    # =========================================================================
    # Node 3: Evidence Validation
    # =========================================================================
    def _node_validate_evidence(self, state: IntelligenceGraphState) -> IntelligenceGraphState:
        """Validates claims, single-source boundaries, and guards against prompt injections."""
        candidates = state.get("candidate_clusters", [])
        specialist_results = state.get("specialist_results", {})
        existing_validations = state.get("evidence_results", {})

        new_validations: Dict[str, EvidenceValidationResult] = dict(existing_validations)

        for cand in candidates:
            cl_id = cand.cluster_id
            if cl_id in new_validations:
                continue

            analysis = specialist_results.get(cl_id)
            if not analysis:
                continue

            validation = self.validator.validate_specialist_output(
                candidate=cand,
                analysis=analysis,
            )
            new_validations[cl_id] = validation

        logger.info(f"[LangGraph:validate_evidence] Validated evidence for {len(new_validations)} clusters.")
        return {"evidence_results": new_validations}

    # =========================================================================
    # Node 4: Ranking & Story Synthesis
    # =========================================================================
    def _node_rank_and_synthesize(self, state: IntelligenceGraphState) -> IntelligenceGraphState:
        """Filters non-relevant items, synthesizes verified summaries, and ranks final newspaper stories."""
        candidates = state.get("candidate_clusters", [])
        specialist_results = state.get("specialist_results", {})
        evidence_results = state.get("evidence_results", {})
        routes = state.get("domain_routes", {})

        synthesized: Dict[str, StorySynthesisResult] = {}

        for cand in candidates:
            cl_id = cand.cluster_id
            analysis = specialist_results.get(cl_id)
            ev = evidence_results.get(cl_id)

            if not analysis or not ev:
                continue

            # Filter out non-relevant stories or severe prompt injection attacks
            if not analysis.is_relevant or ev.is_prompt_injection_detected:
                logger.info(f"Skipping cluster '{cl_id}' from newspaper (relevant={analysis.is_relevant}, injection={ev.is_prompt_injection_detected})")
                continue

            # Calculate composite priority score
            # Base priority from specialist (50%) + deterministic ranking (35%) + multi-source consensus bonus (15%)
            multi_source_bonus = 0.15 if len(cand.sources) > 1 else 0.0
            composite_score = round(
                (analysis.priority_score * 0.50) + (cand.ranking_score * 0.35) + multi_source_bonus,
                3,
            )

            rep_art = cand.representative_article
            clean_summary = ev.sanitized_summary or analysis.main_development

            # Disclose single-source caveat if only 1 source exists
            if ev.single_source_only and "Reported by" not in clean_summary:
                clean_summary = f"{clean_summary} (Reported by {rep_art.source})"

            final_story = StorySynthesisResult(
                cluster_id=cl_id,
                headline=rep_art.title,
                summary=clean_summary,
                domain=analysis.domain,
                topic=analysis.topic,
                priority_score=composite_score,
                relevance_score=analysis.relevance_score,
                sources=cand.sources or [rep_art.source],
                representative_source=rep_art.source,
                representative_url=rep_art.url,
                source_count=len(cand.sources) if cand.sources else 1,
                key_claims=ev.verified_claims,
                evidence_level=analysis.evidence_level,
                agent_attribution=f"{analysis.domain.upper()} Specialist ({analysis.evidence_level} Evidence)",
            )
            synthesized[cl_id] = final_story

        logger.info(f"[LangGraph:rank_and_synthesize] Formed {len(synthesized)} validated newspaper stories.")
        return {"synthesized_stories": synthesized, "status": "COMPLETED"}

    def run(
        self,
        candidate_clusters: List[CandidateStoryInput],
        run_id: Optional[str] = None,
    ) -> IntelligenceGraphState:
        """Executes the complete compiled LangGraph workflow synchronously."""
        initial_state: IntelligenceGraphState = {
            "run_id": run_id or f"graph_{int(time.time())}",
            "status": "RUNNING",
            "started_at": datetime.utcnow().isoformat(),
            "execution_mode": "LANGGRAPH_MULTI_AGENT",
            "candidate_clusters": candidate_clusters,
            "domain_routes": {},
            "specialist_results": {},
            "evidence_results": {},
            "synthesized_stories": {},
            "retry_counts": {},
            "errors": [],
            "llm_call_count": 0,
            "qwen_evaluations_avoided": 0,
            "fallback_count": 0,
            "duration_seconds": 0.0,
        }

        start_time = time.time()
        final_state = self.graph.invoke(initial_state)
        final_state["duration_seconds"] = round(time.time() - start_time, 2)
        return final_state
