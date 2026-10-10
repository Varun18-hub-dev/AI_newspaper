import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import time
from app.llm.qwen import QwenProvider

p = QwenProvider(max_tokens=256)
prompt = """You are an AI Researcher. Return ONLY valid JSON:
{
  "is_relevant": true,
  "relevance_score": 0.95,
  "topic": "LLMs",
  "main_development": "Anthropic released Claude 3.5 Sonnet with major coding advances.",
  "key_claims": ["Outperforms GPT-4o on HumanEval", "Operates at 2x speed"],
  "evidence_level": "STRONG",
  "priority_score": 0.90,
  "priority_rationale": "Major foundation model benchmark."
}
Article: Anthropic announced Claude 3.5 Sonnet with state-of-the-art coding benchmarks.
"""

t0 = time.time()
res = p.generate(prompt)
t1 = time.time()
print(f"Generated in {t1 - t0:.2f}s:")
print(res)
