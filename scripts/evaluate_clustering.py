"""Evaluation script for Phase 4 semantic story deduplication and clustering.

Evaluates precision, recall, F1, false merges, and missed duplicates
across positive pairs and negative pairs.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.clustering.clusterer import StoryClusterer
from app.ingestion.models import Article


def load_eval_dataset(dataset_path: Path) -> List[Dict[str, Any]]:
    """Loads annotated clustering test pairs."""
    with open(dataset_path, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_pairs(clusterer: StoryClusterer, dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Runs pairwise clustering evaluation and returns metrics."""
    tp, fp, tn, fn = 0, 0, 0, 0
    results = []

    for item in dataset:
        pair_id = item["id"]
        expected = item["expected_cluster"]
        cat = item.get("category", "")

        art_a = Article(**item["article_a"])
        art_b = Article(**item["article_b"])

        clusters, _ = clusterer.cluster_articles([art_a, art_b])
        # If both articles ended up in 1 cluster, predicted = True; if 2 clusters, predicted = False
        predicted = (len(clusters) == 1)

        is_correct = (predicted == expected)
        if expected and predicted:
            tp += 1
            status = "TP (Correct Merge)"
        elif not expected and not predicted:
            tn += 1
            status = "TN (Correct Separation)"
        elif not expected and predicted:
            fp += 1
            status = "FP (FALSE MERGE)"
        else:
            fn += 1
            status = "FN (MISSED DUPLICATE)"

        results.append({
            "id": pair_id,
            "category": cat,
            "title_a": art_a.title[:45],
            "title_b": art_b.title[:45],
            "expected": expected,
            "predicted": predicted,
            "status": status,
            "correct": is_correct,
        })

    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = (tp + tn) / len(dataset) if dataset else 0.0

    return {
        "total_pairs": len(dataset),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision * 100.0, 2),
        "recall": round(recall * 100.0, 2),
        "f1": round(f1 * 100.0, 2),
        "accuracy": round(accuracy * 100.0, 2),
        "results": results,
    }


def main():
    root_dir = Path(__file__).resolve().parent.parent
    eval_file = root_dir / "tests" / "data" / "clustering_eval_dataset.json"

    print("=" * 80)
    print("PHASE 4: SEMANTIC STORY DEDUPLICATION & CLUSTERING EVALUATION")
    print("=" * 80)
    print(f"Loading evaluation pairs from: {eval_file}")

    dataset = load_eval_dataset(eval_file)
    print(f"Loaded {len(dataset)} evaluation pairs.\n")

    clusterer = StoryClusterer()
    metrics = evaluate_pairs(clusterer, dataset)

    print("-" * 80)
    print("PAIRWISE EVALUATION RESULTS:")
    print("-" * 80)
    print(f"{'Pair ID':<32} | {'Expected':<8} | {'Predicted':<9} | {'Status'}")
    print("-" * 80)
    for r in metrics["results"]:
        exp_str = "MERGE" if r["expected"] else "SEPARATE"
        pred_str = "MERGE" if r["predicted"] else "SEPARATE"
        print(f"{r['id']:<32} | {exp_str:<8} | {pred_str:<9} | {r['status']}")

    print("\n" + "=" * 80)
    print("SUMMARY PERFORMANCE METRICS:")
    print("=" * 80)
    print(f"Total Test Pairs:           {metrics['total_pairs']}")
    print(f"True Positives (Merged):    {metrics['tp']}")
    print(f"True Negatives (Separated): {metrics['tn']}")
    print(f"False Merges (FP):          {metrics['fp']} (Unsafe merge count)")
    print(f"Missed Duplicates (FN):     {metrics['fn']}")
    print(f"Pairwise Precision:         {metrics['precision']}%")
    print(f"Pairwise Recall:            {metrics['recall']}%")
    print(f"F1-Score:                   {metrics['f1']}%")
    print(f"Overall Accuracy:           {metrics['accuracy']}%")
    print("=" * 80)

    # Low false merges is strictly required:
    if metrics["fp"] == 0:
        print("\n[OK] Zero false merges achieved (100% Precision on safe separation).")
    else:
        print(f"\n[WARNING] {metrics['fp']} false merges detected!")

    if metrics["recall"] >= 90.0:
        print(f"[OK] High recall achieved ({metrics['recall']}% >= 90.0%).")
    else:
        print(f"[WARNING] Recall below target ({metrics['recall']}% < 90.0%).")


if __name__ == "__main__":
    main()
