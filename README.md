# Personalized AI Newspaper - Phase 1, 2, 3 & 3.1

## Project Purpose
**Personalized AI Newspaper** is an agentic system designed to discover, filter, personalize, summarize, and deliver relevant information from the internet based on each user's selected domains (e.g., AI, Cybersecurity, Cloud, Open Source).

- **Phase 1 (Completed):** Established modular project foundation, provider-agnostic LLM interface, and validated local **Qwen 2.5 3B (3.1B parameters, Q4_K_M)** structured JSON inference via Ollama.
- **Phase 2 (Completed):** Built the end-to-end information discovery pipeline for the **AI / Artificial Intelligence** domain (RSS ingestion -> normalization -> deterministic filtering -> Qwen relevance classification).
- **Phase 3 (Completed):** Built article webpage content fetching, main prose extraction & text cleaning (`BeautifulSoup4` + `lxml`), and introduced deterministic pre-filtering.
- **Phase 3.1 (Completed):** Pipeline Optimization & Latency Reduction:
  - Profiled latency bottlenecks (prompt token evaluation on CPU).
  - Compacted prompt and capped generation tokens (`MAX_TOKENS=128`), cutting average Qwen latency by ~38% (from 63.8s down to ~39.1s).
  - Upgraded deterministic pre-filter to multi-signal scoring with **0 false negatives (100.0% recall, 95.5% precision, 97.7% F1)**.
  - Implemented multi-factor deterministic candidate ranking (relevance, source authority, freshness).
  - Implemented Top-K candidate selection (`QWEN_MAX_CANDIDATES=10`).
  - Implemented a controlled topic taxonomy (`ALLOWED_TOPICS`) with automated normalization.

---

## Target Discovery Pipeline (Phase 3.1)

```text
RSS Sources (TechCrunch, The Verge, Hugging Face, Ars Technica)
     ↓
Article Metadata (55 articles)
     ↓
URL / Basic Filtering (55 valid, unique)
     ↓
Fetch Article Webpage & Extract Prose (BeautifulSoup4 + lxml)
     ↓
Multi-Signal Deterministic Pre-Filter (Recall = 100%, 0 false negatives)
     ↓
Candidate Ranking (Multi-factor: relevance 70%, source 25%, freshness 5%)
     ↓
Top-K Selection (Configurable: QWEN_MAX_CANDIDATES=10)
     ↓
Fast Qwen Relevance Classification (Compact prompt, max_tokens=128, avg 39.1s)
     ↓
Structured AI News Candidates (Standardized topic taxonomy)
```

---

## Project Structure

```text
AI_newspaper/
│
├── app/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py             # Environment configuration (Pydantic Settings)
│   │   └── logging.py            # Centralized logging setup
│   │
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── models.py             # Normalized Article Pydantic model
│   │   └── rss.py                # RSS/Atom connector with retry resilience
│   │
│   ├── extraction/
│   │   ├── __init__.py
│   │   ├── models.py             # ExtractedContent model
│   │   ├── fetcher.py            # WebPageFetcher (resilient HTTP session & retry)
│   │   ├── extractor.py          # ContentExtractor (BeautifulSoup DOM extraction)
│   │   └── cleaner.py            # Text cleaner & sentence-aware smart truncation
│   │
│   ├── processing/
│   │   ├── __init__.py
│   │   ├── models.py             # ProcessedArticle, PipelineMetrics, ALLOWED_TOPICS
│   │   ├── filtering.py          # URL normalization & deduplication
│   │   ├── pre_filter.py         # DeterministicPreFilter (multi-signal & ranking)
│   │   └── article_processor.py  # Top-K ranking, compact prompt, Qwen classification
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py               # Generic LLMProvider ABC & custom exceptions
│   │   └── qwen.py               # QwenProvider implementation over Ollama API
│   │
│   └── main.py                   # Phase 1 verification entry point
│
├── tests/
│   ├── __init__.py
│   ├── test_qwen.py              # Phase 1 unified test suite
│   ├── test_qwen_unit.py         # Phase 1 unit tests
│   ├── test_qwen_integration.py  # Phase 1 live model integration tests
│   ├── test_phase2_unit.py       # Phase 2 unit tests (ingestion, models, filtering)
│   ├── test_phase2_integration.py# Phase 2 live RSS & Qwen integration tests
│   ├── test_phase3_unit.py       # Phase 3 unit tests (fetcher, extractor, cleaner)
│   ├── test_phase3_integration.py# Phase 3 live webpage extraction & pre-filter integration
│   └── test_phase3_1_optimization.py # Phase 3.1 unit tests (ranking, taxonomy, prompt, top-k)
│
├── scripts/
│   ├── test_qwen.py              # Standalone Qwen verification script (Phase 1)
│   ├── run_ai_discovery.py       # Phase 3.1 AI discovery CLI with live telemetry
│   ├── evaluate_recall.py        # Ground-truth precision & recall evaluator
│   └── benchmark_batch_sizes.py  # Batch size & latency benchmarking script
│
├── .env.example                  # Template for environment configuration
├── .gitignore                    # Git exclusions
├── requirements.txt              # Core project dependencies
└── README.md                     # Project documentation
```

---

## Configuration

Configuration values are managed by `app/core/config.py`:

| Variable | Default Value | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama HTTP API endpoint |
| `MODEL_NAME` | `qwen2.5:3b` | Target local model name |
| `TEMPERATURE` | `0.0` | Sampling temperature for deterministic structured outputs |
| `MAX_TOKENS` | `128` | Output token generation limit (classification efficiency) |
| `REQUEST_TIMEOUT`| `180.0` | Request timeout in seconds |
| `AI_RSS_FEEDS` | 4 reliable tech/AI feeds | Comma-separated RSS/Atom feed URLs |
| `MAX_ITEMS_PER_FEED` | `15` | Max articles to ingest per feed |
| `MAX_CLASSIFY_CANDIDATES` | `10` | Candidate classification limit |
| `QWEN_MAX_CANDIDATES` | `10` | Top-K candidate ranking selection limit |
| `ENABLED_DOMAINS` | `ai,technology,science,cybersecurity,business` | Enabled news domains |
| `DB_PATH` | `data/newspaper.db` | SQLite database file location |
| `SCHEDULE_ENABLED` | `true` | Daily scheduler enablement flag |
| `SCHEDULE_TIME` | `06:00` | Scheduled daily run time in 24h format |
| `SCHEDULE_TIMEZONE` | `Asia/Kolkata` | IANA timezone (default: Asia/Kolkata, e.g. UTC, America/New_York) |
| `SCHEDULE_LOCK_FILE` | `data/pipeline.lock` | File lock path for cross-process concurrency guard |
| `SCHEDULE_RUN_ON_STARTUP` | `false` | Run immediately on boot if today's run hasn't completed |
| `LOG_LEVEL` | `INFO` | Console log verbosity |

---

## Phase 7: Daily Scheduling & Automation

Phase 7 introduces automated daily execution and operational run lifecycle telemetry:
1. **Configurable Daily Execution:** Runs daily at a user-configured time (`SCHEDULE_TIME`) and IANA timezone (`SCHEDULE_TIMEZONE`).
2. **Restart Duplicate Prevention:** On daemon restart, queries the SQLite database for today's completed runs in the target timezone. If today's scheduled run already completed, skips duplicate execution and schedules for tomorrow.
3. **Dual Overlap Prevention:** Combines an in-process `threading.Lock` and a cross-process file lock via `portalocker` (`data/pipeline.lock`) to prevent concurrent manual and scheduled executions.
4. **Lifecycle & Telemetry Tracking:** Records all execution metadata in SQLite (`pipeline_runs` table): run ID, trigger type (`SCHEDULED` vs. `MANUAL`), duration, start/end timestamps, status (`RUNNING`, `SUCCESS`, `PARTIAL_SUCCESS`, `FAILED`), article and cluster counts, Qwen evaluations, domain breakdown, and feed error logs.

---

## Controlled Topic Taxonomy

The system enforces controlled taxonomies across all 5 domains:
- **AI:** `AI Agents`, `LLMs`, `Generative AI`, `AI Safety`, `Machine Learning`, `Computer Vision`, `NLP`, `Robotics`, `AI Infrastructure`, `AI Hardware`, `AI Research`, `AI Startups`, `Other`
- **Technology:** `Software & Apps`, `Hardware & Devices`, `Consumer Tech`, `Cloud Computing`, `Mobile & Telecom`, `Operating Systems`, `Semiconductors`, `Internet & Web`, `Other`
- **Science:** `Space & Astronomy`, `Physics`, `Biology & Genetics`, `Medicine & Health`, `Climate & Earth`, `Materials Science`, `Neuroscience`, `Other`
- **Cybersecurity:** `Vulnerabilities & CVEs`, `Data Breaches`, `Malware & Ransomware`, `Threat Actors & APTs`, `Application Security`, `Network & Cloud Security`, `Security Policy & Compliance`, `Other`
- **Business:** `Venture Capital & Funding`, `Startups`, `M&A and IPOs`, `Tech Giants & Big Tech`, `Regulation & Antitrust`, `Leadership & Executive`, `Markets & Economy`, `Other`

---

---

## Phase 8: End-to-End Integration & Next.js Web Application

Phase 8 integrates the multi-domain discovery pipeline, story clustering, and persistent storage into a web application:
1. **FastAPI REST API (`app/api/`):**
   - Health and storage telemetry: `GET /api/health`
   - Configured domains & taxonomies: `GET /api/domains`
   - Paginated curated newspaper edition: `GET /api/newspaper/latest`
   - Multi-source story detail breakdown: `GET /api/newspaper/stories/{cluster_id}`
   - Pipeline run telemetry & history: `GET /api/runs` and `GET /api/runs/latest`
   - Non-blocking manual discovery trigger: `POST /api/runs/refresh` (returns `202 Accepted` or `409 Conflict` if locked)
2. **Next.js Web Frontend (`frontend/`):**
   - Classic newspaper masthead styling with responsive typography.
   - Section navigation across all domains (AI, Technology, Science, Cybersecurity, Business) with story count badges.
   - Controlled subtopic taxonomy filtering.
   - Lead story feature on Page 1 and multi-source story cards with coverage indicators and breaking update tags.
   - Interactive story detail modal with constituent member article links and deduplication explainers.
   - Real-time diagnostics modal and on-demand refresh trigger with polling.

---

## Phase 8.1: Agentic Intelligence Layer with LangGraph

Phase 8.1 introduces an agentic news intelligence workflow using LangGraph:
1. **LangGraph Stateful Orchestration (`app/intelligence/`):**
   - Explicit typed state (`IntelligenceGraphState`) coordinating run ID, candidate story clusters, domain routing, evidence validations, and synthesis.
   - Sequential graph: `route_domains` → `specialist_analysis` → `validate_evidence` → `rank_and_synthesize`.
2. **5 Domain-Specialized Researcher Agents:**
   - AI Researcher, Technology Researcher, Science Researcher, Cybersecurity Researcher, Business & Startups Researcher.
   - Analyzes candidate stories, extracts grounded claims, assigns priority scores, and prevents cross-domain hallucinations.
3. **Evidence & Prompt-Injection Defense:**
   - Wraps untrusted webpage prose in strict security delimiters (`<article_content>`).
   - Scans for instruction override and jailbreak patterns, automatically quarantining adversarial text.
   - Enforces single-source attribution and verifies factual claim grounding.
4. **CrewAI Evaluation Benchmark:**
   - Evaluated Deterministic Baseline vs. LangGraph vs. CrewAI Multi-Agent.
   - CrewAI incurred a **300% inflation in LLM call volume and latency** without precision gains on local CPU; LangGraph was selected for production orchestration.

---

## How to Run

### 1. Launch FastAPI Backend Server
Run the REST API backend on port 8000:
```bash
python scripts/run_api.py --port 8000
```
- OpenAPI Documentation: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/api/health`

### 2. Launch Next.js Web Application
In a separate terminal, start the Next.js development server:
```bash
cd frontend
npm run dev
```
- Web Application: `http://localhost:3000`
- Connects automatically to the backend at `http://127.0.0.1:8000` (configurable via `NEXT_PUBLIC_API_URL`).

### 3. Run Comparative Agentic Benchmark (LangGraph vs CrewAI)
```bash
python scripts/benchmark_agentic_eval.py
```

### 4. Run Verification Audit Script
```bash
python scripts/verify_phase8_e2e.py
```

### 5. Manual Discovery Pipeline Run (`--now`)
Run the pipeline immediately and display run telemetry:
```bash
python scripts/run_scheduler.py --now
```

### 6. Run Daily Scheduler Daemon (`--daemon`)
Run the persistent background scheduler:
```bash
python scripts/run_scheduler.py --daemon --time 06:00 --timezone UTC
```

### 7. Run Full Regression Test Suite (Phases 1–8.1)
```bash
pytest tests/test_qwen_unit.py tests/test_phase2_unit.py tests/test_phase3_unit.py tests/test_phase3_1_optimization.py tests/test_phase4_clustering_unit.py tests/test_phase5_storage_unit.py tests/test_phase5_cross_day_integration.py tests/test_phase6_multi_domain.py tests/test_phase7_scheduling.py tests/test_phase8_api.py tests/test_phase8_e2e_integration.py tests/test_phase8_1_agentic_intelligence.py -v
```
All **139 tests** pass with 100% success rate.

