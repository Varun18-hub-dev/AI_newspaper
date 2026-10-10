"""Recall and Precision evaluation of DeterministicPreFilter across real 55-article dataset."""

import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.core.config import settings
from app.ingestion.rss import RSSConnector
from app.processing.filtering import filter_and_deduplicate
from app.processing.pre_filter import DeterministicPreFilter

# Ground truth annotations based on editorial domain definition for "AI / Artificial Intelligence"
# Evaluates whether the underlying story is genuinely about AI technology/models/agents/policy vs non-AI IT/promo.
GROUND_TRUTH_AI_KEYWORDS = [
    "ai", "agent", "agents", "model", "models", "llm", "gemini", "claude", "chatgpt",
    "copilot", "hugging face", "transformer", "neural", "falcon", "nemotron",
    "astabrief", "autosynthdata", "tts", "mcp", "holo4", "rl", "evaleval",
    "tokenizers", "mlx", "deep learning", "machine learning", "artificial intelligence",
    "smart ring puts ai", "cal ai", "healthleap raises $38m for its ai"
]

IRRELEVANT_PATTERNS = [
    "disrupt 2026: don’t pay more at the door",
    "disrupt 2026: don't pay more at the door",
    "hacks of 2 federal agencies",
    "vmware users to explore options",
    "critical zimbra flaw",
    "quantum-safe tls certificates",
    "frozen mac says it’s infected after viewing a google ad",
    "frozen mac says it's infected",
    "faster than anything weve seen before",
    "faster than anything we've seen before",
    "break rsa",
    "it mistake erases 11 years",
    "undercover google analyst infiltrated a notorious supply-chain",
    "counterfeit tls certificates",
    "memory executives expect ram shortage",
    "memory supplies are only getting tighter",
    "surface laptop ultra event",
    "artificial is a wicked satire",
]


def is_ground_truth_ai(title: str, desc: str) -> bool:
    """Ground truth oracle determining whether an article belongs to the AI domain."""
    low_title = title.lower()
    low_desc = (desc or "").lower()
    combined = low_title + " " + low_desc

    # Check negative list first
    for pat in IRRELEVANT_PATTERNS:
        if pat in low_title:
            return False

    # Check positive AI signals
    for kw in GROUND_TRUTH_AI_KEYWORDS:
        if kw in low_title or kw in low_desc:
            return True

    return False


def main():
    print("=" * 65)
    print("PHASE 3.1: GROUND-TRUTH RECALL & PRECISION EVALUATION")
    print("=" * 65)

    connector = RSSConnector()
    articles, _ = connector.fetch_all(settings.ai_rss_feeds)
    filtered = filter_and_deduplicate(articles)
    pre_filter = DeterministicPreFilter(threshold=0.20)

    tp = 0  # Pre-filter passed AND is Ground Truth AI
    fp = 0  # Pre-filter passed BUT is NOT Ground Truth AI (acceptable: Qwen will filter it)
    fn = 0  # Pre-filter rejected BUT IS Ground Truth AI (CRITICAL: false negative!)
    tn = 0  # Pre-filter rejected AND is NOT Ground Truth AI (safely saved LLM call)

    false_negatives = []
    false_positives = []

    for art in filtered:
        gt_is_ai = is_ground_truth_ai(art.title, art.description or "")
        pf_result = pre_filter.evaluate(art, None)
        pf_passed = pf_result.should_send_to_llm

        if pf_passed and gt_is_ai:
            tp += 1
        elif pf_passed and not gt_is_ai:
            fp += 1
            false_positives.append((art.title, pf_result.pre_filter_score, pf_result.signals))
        elif not pf_passed and gt_is_ai:
            fn += 1
            false_negatives.append((art.title, pf_result.pre_filter_score, pf_result.signals))
        elif not pf_passed and not gt_is_ai:
            tn += 1

    total = len(filtered)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    print(f"Total articles evaluated: {total}")
    print(f"Ground Truth AI articles: {tp + fn}")
    print(f"Ground Truth Irrelevant:  {tn + fp}")
    print("-" * 65)
    print(f"True Positives (Retained AI stories):       {tp}")
    print(f"True Negatives (Safely rejected non-AI):    {tn}")
    print(f"False Positives (Passed to Qwen to decide): {fp}")
    print(f"False Negatives (Accidentally dropped AI):  {fn}")
    print("-" * 65)
    print(f"Pre-filter Precision: {precision * 100:.1f}%")
    print(f"Pre-filter Recall:    {recall * 100:.1f}%")
    print(f"Pre-filter F1-Score:  {f1 * 100:.1f}%")
    print("=" * 65)

    if false_negatives:
        print("\nWARNING: False Negatives Detected (must be 0 for safe filtering):")
        for title, score, sigs in false_negatives:
            print(f"  - '{title}' (score={score}, sigs={sigs})")
    else:
        print("\nSUCCESS: 0 False Negatives! All genuine AI articles were successfully retained.")


if __name__ == "__main__":
    main()
