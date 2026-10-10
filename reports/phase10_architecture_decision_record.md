# Phase 10 Architecture Decision Record (ADR)
## Zero-Cost Baseline & Serverless Deployment Architecture

- **Status:** APPROVED & VALIDATED LOCALLY
- **Date:** October 10, 2026
- **Context:** Personalized AI Newspaper — Transitioning from Development to Zero-Cost Baseline & Optional GPU Production

---

## 1. Executive Summary

This Architecture Decision Record (ADR) defines the verified, zero-cost production baseline and low-cost GPU architecture for the Personalized AI Newspaper. 

Through code inspection, implementation of serverless Next.js reader routes, and validation of deterministic CPU summarization, we have demonstrated that:
1. **The always-on FastAPI server can be completely eliminated for the reader tier**, saving **$4.00–$15.00/month** in server costs.
2. **The daily pipeline can run in a 100% deterministic, CPU-only mode** on GitHub Actions free-tier runners ($0.00/month) or cheap standard compute, generating source-grounded summaries without any generative LLM calls or cloud GPU charges.
3. **Optional GPU synthesis (LangGraph + Qwen 2.5 3B)** remains preserved behind configuration flags (`--agentic`, `ENABLE_GPU_INFERENCE=true`), allowing high-value editorial synthesis on an ephemeral EC2 Spot worker for **$5.09–$5.89/month**.
4. **Browsers require zero AWS credentials**, reading published editions through Next.js serverless routes or CDN caching with optimal cache invalidation.

---

## 2. Architecture Comparison

| Dimension | Architecture A: Always-On FastAPI + GPU Worker | Architecture B: Low-Cost GPU Worker + S3 + Next.js Serverless | Architecture C: Zero-Cost Baseline (GitHub Actions CPU + Vercel) |
| :--- | :--- | :--- | :--- |
| **Reader Tier** | Always-on t4g.small / ECS container | Next.js Serverless API on Vercel Free / Netlify | Next.js Serverless API on Vercel Free |
| **Reader Monthly Cost** | $4.20 - $14.60 / mo | **$0.00 / mo** (Free Tier) | **$0.00 / mo** (Free Tier) |
| **Compute Worker** | Daily EC2 GPU Worker (g4dn.xlarge) | Daily EC2 Spot GPU Worker (g4dn.xlarge) | GitHub Actions Free Runner (Ubuntu CPU) |
| **Worker Invocations** | 1 daily run (~18-20 min) | 1 daily run (~18-20 min Spot) | 1 daily run (~1.5 min CPU) |
| **Worker Compute Cost**| $2.84 / mo (On-Demand) | **$1.13 / mo** (Spot) | **$0.00 / mo** (2,000 free min/mo) |
| **Intelligence Layer** | LangGraph + Qwen 2.5 3B (GPU) | LangGraph + Qwen 2.5 3B (GPU) | **Deterministic Source-Grounded** (CPU) |
| **Story Summarization** | Multi-agent synthesis | Multi-agent synthesis | Clean lead extraction & taxonomy matching |
| **Storage & Editions** | S3 Standard + DynamoDB/EBS | S3 Standard (~0.05 GB) | S3 Standard / GitHub Artifacts / Vercel Blob |
| **Total Monthly Cost** | **$11.80 - $22.40 / mo** | **$5.09 - $5.89 / mo** | **$0.00 / mo** |

---

## 3. Detailed Component Architecture

### 3.1 Elimination of the Always-On Reader Tier
In Phase 8 and Phase 9B, reading newspaper editions required a running FastAPI backend daemon (`python scripts/run_api.py`) exposing `/api/newspaper/latest`.

**The Solution:**
We implemented native Next.js API Routes in `frontend/pages/api/`:
- `frontend/pages/api/newspaper/latest.js`: Ingests `domain`, `topic`, `page`, and `page_size` query parameters, evaluates edition staleness (>24h), slices the manifest array, and returns `PaginatedStoriesResponse`.
- `frontend/pages/api/newspaper/stories/[id].js`: Resolves story cluster details and publishing source members directly from the edition manifest.
- `frontend/pages/api/domains.js`: Serves the 5-domain taxonomy with dynamic story counts derived from the active edition manifest.
- `frontend/pages/api/health.js`: Health readiness probe reporting serverless mode and active edition pointer status.
- `frontend/pages/api/runs/latest.js`: Run telemetry reporting execution status and edition timestamp.

**Reader Client Configuration:**
In `frontend/lib/api.js`, `API_BASE_URL` now defaults to `process.env.NEXT_PUBLIC_API_URL || ''`. When no external backend URL is specified, the browser executes relative requests (`/api/...`), routed directly to Next.js Serverless Functions on Vercel or Node.js.

### 3.2 Deterministic CPU-Only Mode
For scenarios where zero cloud compute charges are required, the pipeline supports a CPU-only mode:
- **Flag / Toggle:** CLI argument `--cpu-only`, environment variable `CPU_ONLY_MODE=true`, or `enable_llm_inference=False`.
- **Ingestion & Filtering:** Retains the full 23 publisher RSS/Atom feeds, arXiv API, Hacker News API, GitHub API, and NVD CVE ingestion.
- **Deduplication & Clustering:** Runs semantic clustering using the local **ONNX Runtime MiniLM** (`all-MiniLM-L6-v2`), executing on standard CPU in **<150 milliseconds**.
- **Summarization:** `classify_article_deterministic()` in `app/processing/article_processor.py` extracts 2–3 lead sentences from cleaned readability text or article description, ensuring source-grounded excerpts without LLM hallucination or inference latency.
- **Taxonomy Classification:** Matches subtopics deterministically against domain keywords defined in `app/domains/registry.py`.
- **Validation:** Produces compliant `EditionStory` objects that pass all `EditionValidator` constraints (valid URLs, minimum length > 10 chars, valid source attribution).

### 3.3 Optional GPU Synthesis Mode
The GPU synthesis pipeline created in Phase 8.1 and 9B remains completely intact:
- Activated via `--agentic` or `ENABLE_AGENTIC_INTELLIGENCE=true`.
- Invokes LangGraph multi-agent orchestration with local Qwen 2.5 3B running via Ollama.
- Graceful Fallback: If `ENABLE_LLM_INFERENCE=true` but Ollama is offline or uncontactable, `ArticleProcessor` automatically falls back to deterministic source-grounded summarization, preventing pipeline crashes or empty publication failures.

---

## 4. Key Verification & Architectural Invariants

### 4.1 Self-Contained Edition Manifest
Audited `EditionManifest` and `EditionStory` schemas in `app/storage/publisher.py`. The manifest JSON includes:
- `edition_id`, `publication_date`, `published_at`, `checksum`
- `domain_counts`, `sources_represented`, `total_stories`
- Every `EditionStory` contains `story_id`, `title`, `url`, `domain`, `topic`, `summary`, `sources`, `published_at`, `first_seen_at`, `relevance_score`, `image_url`, and `raw_metadata`.

**Result:** The reader tier does NOT require SQLite access or database connections to display the newspaper or story details.

### 4.2 Zero-Credential S3 Access Pattern
Browser clients NEVER receive AWS access keys or secrets:
- **Public S3 / CloudFront Pattern:** S3 bucket policy allows `s3:GetObject` only on `/editions/*` and `current_edition.json`. CloudFront serves these assets over HTTPS.
- **Serverless Fetch Pattern:** Next.js API route fetches editions server-side using server environment variables (`EDITIONS_BASE_URL` or S3 client), streaming the sanitized JSON to the browser.
- **Cache-Control Headers:**
  - `current_edition.json`: `Cache-Control: public, s-maxage=60, stale-while-revalidate=300` (short TTL enables immediate discovery of new editions).
  - `editions/{edition_id}.json`: `Cache-Control: public, max-age=31536000, immutable` (immutable daily archive).

### 4.3 GitHub Actions Ephemeral Filesystem Mitigation
GitHub Actions runners run in ephemeral virtual machines; `data/newspaper.db` is destroyed upon runner termination.
**Mitigation Strategy for Scheduled CPU Publication:**
```yaml
name: Daily CPU Publication
on:
  schedule:
    - cron: '30 0 * * *' # 06:00 IST daily
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Download historical deduplication database
        run: aws s3 cp s3://${{ secrets.S3_BUCKET }}/data/newspaper.db data/newspaper.db || true
      - name: Run CPU pipeline
        run: python scripts/run_daily_edition.py --cpu-only --storage-backend s3
      - name: Persist updated database back to S3
        run: aws s3 cp data/newspaper.db s3://${{ secrets.S3_BUCKET }}/data/newspaper.db
```

### 4.4 Atomic Publication Integrity
1. Candidate edition is assembled and validated through `EditionValidator` (`min_stories >= 3`, valid URLs, non-empty summaries).
2. If valid, `editions/{edition_id}.json` is uploaded immutably.
3. `current_edition.json` pointer is uploaded atomically.
4. If validation fails at any point, the pointer remains completely untouched, ensuring readers always see the last known good edition.

### 4.5 Edge Case Handling
- **Stale Edition:** If `Date.now() - published_at > 24h`, the reader API sets `is_stale: true`, rendering an editorial advisory banner.
- **Missing Edition:** Next.js route returns empty state `{ items: [], total: 0 }` with HTTP 200 rather than crashing.
- **Malformed JSON:** Caught via `try...catch` and logged; falls back safely to null without unhandled process crashes.
- **Broken / Missing Images:** Verified through `ArticleImage.js` with `onError` handling, rendering clean text-first editorial layout with zero layout shift.

---

## 5. Cost Breakdown

### Baseline 1: Zero-Cost Architecture ($0.00 / month)
- **Frontend / Reader:** Vercel Hobby Free Tier (Unlimited static hosting, 100GB bandwidth, 100k serverless function executions/month) -> **$0.00**
- **Compute Worker:** GitHub Actions Free Tier (2,000 Linux build minutes/month; Daily CPU run takes ~1.5 min = ~45 min/month) -> **$0.00**
- **LLM Inference:** Deterministic source-grounded summaries (0 LLM tokens, pure CPU) -> **$0.00**
- **Storage:** AWS S3 Free Tier (5 GB standard storage, 20,000 GET requests) -> **$0.00**
- **Total:** **$0.00 / month**

### Baseline 2: Low-Cost GPU Architecture ($5.09 - $5.89 / month)
- **Frontend / Reader:** Vercel Hobby Free Tier -> **$0.00**
- **Compute Worker:** EC2 Spot `g4dn.xlarge` (1 daily run @ ~18 min/day = 9 hours/month @ $0.1575/hr) -> **$1.42**
- **Worker Coordinator:** AWS Lambda (30 runs/month) + EventBridge Schedule -> **$0.00**
- **Worker EBS Volume:** 30 GB gp3 volume retained while stopped ($0.08/GB-month) -> **$2.40**
- **S3 Edition Storage & Data Transfer:** 30 editions + CloudFront distribution -> **$1.27**
- **Total:** **$5.09 / month**

---

## 6. Verification & Test Execution Summary

### Automated Test Results
- **Full Backend Validation Suite:** 39 passed in 27.99s
  - `tests/test_phase8_api.py` (10 passed)
  - `tests/test_phase9b_orchestration.py` (16 passed)
  - `tests/test_phase10_image_support.py` (7 passed)
  - `tests/test_phase10_deployment_validation.py` (6 passed)
- **Frontend Next.js Production Build:** `npm run build` completed with code 0:
  - Static pages: `/`, `/_app`, `/404`
  - Dynamic Serverless API routes: `/api/domains`, `/api/health`, `/api/newspaper/latest`, `/api/newspaper/stories/[id]`, `/api/runs/latest`, `/api/runs/refresh`

---

## 7. Local Run Instructions

### A. Run Deterministic CPU-Only Publication (Zero-Cost Baseline)
```bash
# Ingests from all sources, runs ONNX clustering, extracts lead summaries, publishes edition
python scripts/run_daily_edition.py --cpu-only
```

### B. Run GPU / Agentic Synthesis Publication (Optional Cloud/Local GPU)
```bash
# Uses Ollama local Qwen 2.5 3B with LangGraph multi-agent synthesis
python scripts/run_daily_edition.py --agentic
```

### C. Run Next.js Reader Tier (Standalone Serverless Reader)
```bash
cd frontend
npm run dev
# Browser visits http://localhost:3000 (reads current_edition.json directly without FastAPI)
```

### D. Run Legacy FastAPI Backend (Optional Backward-Compatible Mode)
```bash
python scripts/run_api.py
```
