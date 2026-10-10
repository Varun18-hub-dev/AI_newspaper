"""Comparative benchmark script for TF-IDF vs all-MiniLM-L6-v2 ONNX on clustering_eval_dataset_v2.json."""

import sys
from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import numpy as np

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.clustering.clusterer import StoryClusterer
from app.clustering.embeddings import (
    EmbeddingProvider,
    MiniLMEmbeddingProvider,
    TFIDFEmbeddingProvider,
)
from app.clustering.entity_guard import EntityGuard
from app.ingestion.models import Article


@dataclass
class BenchmarkResult:
    provider_name: str
    with_guardrails: bool
    init_time_seconds: float
    total_eval_time_seconds: float
    avg_pair_time_ms: float
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    f1: float
    accuracy: float
    false_merges: List[Dict[str, Any]]
    missed_duplicates: List[Dict[str, Any]]
    category_breakdown: Dict[str, Dict[str, int]]
    provenance_breakdown: Dict[str, Dict[str, int]]


class NoOpEntityGuard(EntityGuard):
    """Bypasses entity guardrails to test raw embedding similarity behavior."""

    def is_merge_allowed(self, art_a, art_b, text_a=None, text_b=None):
        return True, "No-op guardrail"

    def compute_semantic_bonus(self, art_a, art_b, text_a=None, text_b=None):
        return 0.0


def evaluate_provider(
    provider_name: str,
    provider: EmbeddingProvider,
    dataset: List[Dict[str, Any]],
    with_guardrails: bool = True,
    similarity_threshold: Optional[float] = None,
) -> BenchmarkResult:
    """Evaluates a single clustering configuration across the benchmark dataset."""
    guard = EntityGuard() if with_guardrails else NoOpEntityGuard()
    
    # Measure threshold default: 0.45 if guardrails, or appropriate default
    thresh = similarity_threshold if similarity_threshold is not None else 0.45
    clusterer = StoryClusterer(
        embedding_provider=provider,
        entity_guard=guard,
        similarity_threshold=thresh,
    )

    tp, fp, tn, fn = 0, 0, 0, 0
    false_merges: List[Dict[str, Any]] = []
    missed_duplicates: List[Dict[str, Any]] = []
    category_breakdown: Dict[str, Dict[str, int]] = {}
    provenance_breakdown: Dict[str, Dict[str, int]] = {}

    eval_start = time.time()
    for item in dataset:
        art_a = Article(**item["article_a"])
        art_b = Article(**item["article_b"])
        expected = item.get("expected_cluster", item.get("expected_merge", True))
        pair_id = item.get("id", item.get("pair_id", "unknown"))
        category = item.get("category", "unclassified")
        provenance = item.get("provenance", "unknown")

        if category not in category_breakdown:
            category_breakdown[category] = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
        if provenance not in provenance_breakdown:
            provenance_breakdown[provenance] = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}

        clusters, _ = clusterer.cluster_articles([art_a, art_b])
        predicted = (len(clusters) == 1)

        if expected and predicted:
            tp += 1
            category_breakdown[category]["tp"] += 1
            provenance_breakdown[provenance]["tp"] += 1
        elif not expected and not predicted:
            tn += 1
            category_breakdown[category]["tn"] += 1
            provenance_breakdown[provenance]["tn"] += 1
        elif not expected and predicted:
            fp += 1
            category_breakdown[category]["fp"] += 1
            provenance_breakdown[provenance]["fp"] += 1
            false_merges.append({
                "pair_id": pair_id,
                "title_a": art_a.title,
                "title_b": art_b.title,
                "category": category,
            })
        else:
            fn += 1
            category_breakdown[category]["fn"] += 1
            provenance_breakdown[provenance]["fn"] += 1
            missed_duplicates.append({
                "pair_id": pair_id,
                "title_a": art_a.title,
                "title_b": art_b.title,
                "category": category,
            })

    total_eval_time = time.time() - eval_start
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = (tp + tn) / len(dataset) if dataset else 0.0

    return BenchmarkResult(
        provider_name=provider_name,
        with_guardrails=with_guardrails,
        init_time_seconds=0.0,  # Will be populated
        total_eval_time_seconds=round(total_eval_time, 4),
        avg_pair_time_ms=round((total_eval_time / len(dataset)) * 1000.0, 2),
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        accuracy=round(accuracy, 4),
        false_merges=false_merges,
        missed_duplicates=missed_duplicates,
        category_breakdown=category_breakdown,
        provenance_breakdown=provenance_breakdown,
    )


def run_benchmark():
    import logging
    logging.getLogger("clusterer").setLevel(logging.WARNING)

    dataset_path = Path("tests/data/clustering_eval_dataset_v2.json")
    if not dataset_path.exists():
        print(f"Error: {dataset_path} does not exist.")
        return

    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    print("=" * 80)
    print(f"PHASE 4.1 CLUSTERING BENCHMARK ON {len(dataset)} EVALUATION PAIRS")
    pos_count = sum(1 for d in dataset if d.get("expected_cluster", d.get("expected_merge", True)))
    neg_count = sum(1 for d in dataset if not d.get("expected_cluster", d.get("expected_merge", True)))
    real_count = sum(1 for d in dataset if d.get("provenance") == "real_collected")
    auth_count = sum(1 for d in dataset if d.get("provenance") == "manually_authored")
    print(f"Composition: {pos_count} Positive pairs, {neg_count} Hard-Negative pairs")
    print(f"Provenance:  {real_count} real_collected, {auth_count} manually_authored")
    print("=" * 80)

    # 1. Benchmark TF-IDF (Production baseline with EntityGuard)
    t0 = time.time()
    tfidf_provider = TFIDFEmbeddingProvider()
    tfidf_init_time = time.time() - t0

    res_tfidf = evaluate_provider("TF-IDF", tfidf_provider, dataset, with_guardrails=True)
    res_tfidf.init_time_seconds = round(tfidf_init_time, 4)

    # 2. Benchmark MiniLM ONNX (With EntityGuard)
    t0 = time.time()
    minilm_provider = MiniLMEmbeddingProvider()
    minilm_init_time = time.time() - t0

    if not minilm_provider.is_available:
        print("MiniLM ONNX provider is NOT available. Skipping MiniLM benchmark.")
        res_minilm = None
        res_minilm_raw = None
    else:
        res_minilm = evaluate_provider(
            "all-MiniLM-L6-v2 ONNX",
            minilm_provider,
            dataset,
            with_guardrails=True,
            similarity_threshold=0.55,  # Appropriate threshold for dense MiniLM cosine
        )
        res_minilm.init_time_seconds = round(minilm_init_time, 4)

        # 3. Benchmark MiniLM ONNX WITHOUT EntityGuard (Ablation test)
        res_minilm_raw = evaluate_provider(
            "all-MiniLM-L6-v2 (No Guardrails)",
            minilm_provider,
            dataset,
            with_guardrails=False,
            similarity_threshold=0.55,
        )
        res_minilm_raw.init_time_seconds = 0.0

    # Print Summary Table
    print("\n" + "-" * 80)
    print(f"{'Metric':<32} | {'TF-IDF (Baseline)':<18} | {'MiniLM ONNX + Guard':<20} | {'MiniLM (No Guard)':<18}")
    print("-" * 80)
    print(f"{'Embedding Dimension':<32} | {'Sparse (Vocabulary)':<18} | {'384 (Dense)':<20} | {'384 (Dense)':<18}")
    print(f"{'Model Load Time':<32} | {f'{res_tfidf.init_time_seconds*1000:.1f} ms':<18} | {f'{res_minilm.init_time_seconds*1000:.1f} ms':<20} | {'N/A':<18}")
    print(f"{'Total Evaluation Time (100 pairs)':<32} | {f'{res_tfidf.total_eval_time_seconds:.3f} s':<18} | {f'{res_minilm.total_eval_time_seconds:.3f} s':<20} | {f'{res_minilm_raw.total_eval_time_seconds:.3f} s':<18}")
    print(f"{'Avg Latency per Pair':<32} | {f'{res_tfidf.avg_pair_time_ms:.2f} ms':<18} | {f'{res_minilm.avg_pair_time_ms:.2f} ms':<20} | {f'{res_minilm_raw.avg_pair_time_ms:.2f} ms':<18}")
    print(f"{'True Positives (TP)':<32} | {res_tfidf.tp:<18} | {res_minilm.tp:<20} | {res_minilm_raw.tp:<18}")
    print(f"{'True Negatives (TN)':<32} | {res_tfidf.tn:<18} | {res_minilm.tn:<20} | {res_minilm_raw.tn:<18}")
    print(f"{'False Positives (FP - False Merges)':<32} | {res_tfidf.fp:<18} | {res_minilm.fp:<20} | {res_minilm_raw.fp:<18}")
    print(f"{'False Negatives (FN - Missed Dups)':<32} | {res_tfidf.fn:<18} | {res_minilm.fn:<20} | {res_minilm_raw.fn:<18}")
    print(f"{'Precision':<32} | {f'{res_tfidf.precision*100:.1f}%':<18} | {f'{res_minilm.precision*100:.1f}%':<20} | {f'{res_minilm_raw.precision*100:.1f}%':<18}")
    print(f"{'Recall':<32} | {f'{res_tfidf.recall*100:.1f}%':<18} | {f'{res_minilm.recall*100:.1f}%':<20} | {f'{res_minilm_raw.recall*100:.1f}%':<18}")
    print(f"{'F1 Score':<32} | {f'{res_tfidf.f1*100:.1f}%':<18} | {f'{res_minilm.f1*100:.1f}%':<20} | {f'{res_minilm_raw.f1*100:.1f}%':<18}")
    print(f"{'Accuracy':<32} | {f'{res_tfidf.accuracy*100:.1f}%':<18} | {f'{res_minilm.accuracy*100:.1f}%':<20} | {f'{res_minilm_raw.accuracy*100:.1f}%':<18}")
    print("-" * 80)

    # Detailed Analysis
    print("\n" + "=" * 80)
    print("ANALYSIS OF ABLATION & GUARDRAIL IMPORTANCE:")
    print("=" * 80)
    if res_minilm_raw.fp > 0:
        print(f"CRITICAL FINDING: Raw MiniLM WITHOUT EntityGuard produced {res_minilm_raw.fp} FALSE MERGES!")
        print("Sample False Merges in Raw MiniLM:")
        for fm in res_minilm_raw.false_merges[:6]:
            print(f"  - Pair {fm['pair_id']} [{fm['category']}]: '{fm['title_a']}' <-> '{fm['title_b']}'")
    else:
        print("Raw MiniLM produced 0 false merges.")

    if res_minilm.fp == 0:
        print("\nWith EntityGuard enabled:")
        print(f"  - MiniLM + EntityGuard FP: {res_minilm.fp} (100% Precision preserved!)")
        print(f"  - MiniLM + EntityGuard Recall: {res_minilm.recall*100:.1f}% (FN: {res_minilm.fn})")

    if res_tfidf.fp == 0:
        print(f"  - TF-IDF + EntityGuard FP: {res_tfidf.fp} (100% Precision preserved!)")
        print(f"  - TF-IDF + EntityGuard Recall: {res_tfidf.recall*100:.1f}% (FN: {res_tfidf.fn})")

    if res_tfidf.missed_duplicates:
        print("\nTF-IDF Missed Duplicates (FN):")
        for md in res_tfidf.missed_duplicates:
            print(f"  - Pair {md['pair_id']} [{md['category']}]: '{md['title_a']}' <-> '{md['title_b']}'")

    if res_minilm.missed_duplicates:
        print("\nMiniLM Missed Duplicates (FN):")
        for md in res_minilm.missed_duplicates:
            print(f"  - Pair {md['pair_id']} [{md['category']}]: '{md['title_a']}' <-> '{md['title_b']}'")

    # Save results as JSON
    results_dict = {
        "dataset_total_pairs": len(dataset),
        "positive_pairs": pos_count,
        "negative_pairs": neg_count,
        "provenance": {"real_collected": real_count, "manually_authored": auth_count},
        "tfidf": {
            "load_time_seconds": res_tfidf.init_time_seconds,
            "eval_time_seconds": res_tfidf.total_eval_time_seconds,
            "avg_ms_per_pair": res_tfidf.avg_pair_time_ms,
            "tp": res_tfidf.tp,
            "fp": res_tfidf.fp,
            "tn": res_tfidf.tn,
            "fn": res_tfidf.fn,
            "precision": res_tfidf.precision,
            "recall": res_tfidf.recall,
            "f1": res_tfidf.f1,
            "accuracy": res_tfidf.accuracy,
        },
        "minilm_onnx_guarded": {
            "load_time_seconds": res_minilm.init_time_seconds,
            "eval_time_seconds": res_minilm.total_eval_time_seconds,
            "avg_ms_per_pair": res_minilm.avg_pair_time_ms,
            "tp": res_minilm.tp,
            "fp": res_minilm.fp,
            "tn": res_minilm.tn,
            "fn": res_minilm.fn,
            "precision": res_minilm.precision,
            "recall": res_minilm.recall,
            "f1": res_minilm.f1,
            "accuracy": res_minilm.accuracy,
        },
        "minilm_onnx_raw": {
            "eval_time_seconds": res_minilm_raw.total_eval_time_seconds,
            "avg_ms_per_pair": res_minilm_raw.avg_pair_time_ms,
            "tp": res_minilm_raw.tp,
            "fp": res_minilm_raw.fp,
            "tn": res_minilm_raw.tn,
            "fn": res_minilm_raw.fn,
            "precision": res_minilm_raw.precision,
            "recall": res_minilm_raw.recall,
            "f1": res_minilm_raw.f1,
            "accuracy": res_minilm_raw.accuracy,
        },
    }

    out_json = Path("tests/data/clustering_benchmark_results.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results_dict, f, indent=2)
    print(f"\nSaved structured benchmark results to {out_json}")


if __name__ == "__main__":
    run_benchmark()
