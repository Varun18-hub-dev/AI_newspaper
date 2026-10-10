"""Minimal live benchmark using local Ollama qwen2.5:3b model.

Measures actual wall-clock latency, JSON validity, token generation, and retries on real CPU inference.
"""

import os
import sys
import time
from pathlib import Path

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from app.llm.qwen import QwenProvider
from app.ingestion.models import Article
from app.extraction.models import ExtractedContent
from app.intelligence.models import CandidateStoryInput
from app.intelligence.specialists import get_domain_specialist
from app.intelligence.workflow import IntelligenceWorkflow


def main():
    print("=" * 80)
    print("PHASE 8.2 LIVE QWEN 2.5 3B INFERENCE BENCHMARK")
    print("=" * 80)

    # 1. Initialize real QwenProvider
    provider = QwenProvider(model_name="qwen2.5:3b", temperature=0.0, max_tokens=128)
    print(f"Connecting to live Qwen model: {provider.model_name} at {provider.base_url}")

    # 2. Build 1 real candidate cluster for focused live evaluation
    clusters = [
        CandidateStoryInput(
            cluster_id="live_cl_ai_01",
            domain="ai",
            representative_article=Article(
                title="Anthropic launches Claude 3.5 Sonnet with enhanced coding benchmarks",
                url="https://techcrunch.com/claude-35-sonnet",
                source="TechCrunch",
                domain="ai",
                description="Anthropic launched Claude 3.5 Sonnet setting new industry benchmarks in coding and reasoning.",
            ),
            member_articles=[
                Article(title="Anthropic launches Claude 3.5 Sonnet", url="https://techcrunch.com/claude-35-sonnet", source="TechCrunch", domain="ai"),
                Article(title="Claude 3.5 Sonnet available across API", url="https://arstechnica.com/claude-35", source="Ars Technica", domain="ai"),
            ],
            extracted_content=ExtractedContent(
                url="https://techcrunch.com/claude-35-sonnet",
                text="Anthropic launched Claude 3.5 Sonnet with state-of-the-art coding and reasoning benchmarks. Outperforms previous generation on benchmarks.",
                word_count=50,
                extraction_success=True,
            ),
            ranking_score=0.92,
            sources=["TechCrunch", "Ars Technica"],
        ),
    ]

    print(f"\nRunning LangGraph IntelligenceWorkflow over {len(clusters)} live candidate clusters...")
    workflow = IntelligenceWorkflow(llm_provider=provider)

    start_time = time.time()
    final_state = workflow.run(clusters, run_id="live_benchmark_run_01")
    total_time = time.time() - start_time

    print("\n" + "=" * 80)
    print("LIVE INFERENCE RESULTS SUMMARY")
    print("=" * 80)
    print(f"Status: {final_state.get('status')}")
    print(f"Total Wall-Clock Latency: {total_time:.2f} seconds")
    print(f"Total LLM Calls: {final_state.get('llm_call_count')}")
    print(f"Average Latency Per Call: {total_time / max(1, final_state.get('llm_call_count', 1)):.2f} seconds")
    print(f"Fallback Count: {final_state.get('fallback_count')}")

    print("\nPer-Cluster Breakdown:")
    for cl_id, analysis in final_state.get("specialist_results", {}).items():
        print(f"\n[{cl_id}] Domain: {analysis.domain} | Topic: {analysis.topic}")
        print(f"  Role: {analysis.domain.upper()} Specialist")
        print(f"  Relevant: {analysis.is_relevant} (Score: {analysis.relevance_score})")
        print(f"  Main Dev: {analysis.main_development}")
        print(f"  Key Claims: {analysis.key_claims}")
        print(f"  Priority: {analysis.priority_score} | Retries: {analysis.retry_count}")
        print(f"  Fallback Used: {analysis.fallback_used}")

    print("\nFinal Synthesized Newspaper Stories:")
    for cl_id, story in final_state.get("synthesized_stories", {}).items():
        print(f"\nStory [{cl_id}]: {story.headline}")
        print(f"  Summary: {story.summary}")
        print(f"  Attribution: {story.agent_attribution}")
        print(f"  Priority Score: {story.priority_score}")
        print(f"  Sources ({story.source_count}): {', '.join(story.sources)}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
