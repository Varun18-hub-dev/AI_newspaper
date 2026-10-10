"""NVD (National Vulnerability Database) CVE adapter for cybersecurity intelligence."""

from datetime import datetime, timedelta
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.logging import setup_logger
from app.ingestion.adapters.base import BaseSourceAdapter, clean_text, parse_iso_or_rfc_date
from app.ingestion.models import Article

logger = setup_logger("nvd_adapter")


class NVDAdapter(BaseSourceAdapter):
    """Fetches recently published and modified CVEs using the official NVD 2.0 API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        results_per_page: Optional[int] = None,
        timeout: float = 15.0,
        enabled: Optional[bool] = None,
    ):
        super().__init__(
            name="NVD",
            default_domain="Cybersecurity",
            timeout=timeout,
            enabled=enabled if enabled is not None else settings.enable_nvd,
            user_agent="AI-Newspaper/1.0",
        )
        self.api_key = api_key or settings.nvd_api_key
        self.results_per_page = (
            results_per_page if results_per_page is not None else settings.nvd_results_per_page
        )
        self.base_url = "https://services.nvd.nist.gov/rest/json/cves/2.0"

        if self.api_key:
            self.session.headers.update({"apiKey": self.api_key})

    def _extract_cvss(self, metrics: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
        """Extracts CVSS base score and severity from cvssMetricV31, V30, or V2."""
        for metric_key in ["cvssMetricV31", "cvssMetricV30", "cvssMetricV2"]:
            data_list = metrics.get(metric_key, [])
            if data_list and isinstance(data_list, list):
                cvss_data = data_list[0].get("cvssData", {})
                score = cvss_data.get("baseScore")
                severity = (
                    cvss_data.get("baseSeverity")
                    or data_list[0].get("baseSeverity")
                    or "UNKNOWN"
                )
                if score is not None:
                    return float(score), str(severity).upper()
        return None, None

    def parse_cve_item(self, item: Dict[str, Any]) -> Optional[Article]:
        """Converts raw NVD CVE item into an Article model."""
        cve = item.get("cve", {})
        cve_id = cve.get("id")
        if not cve_id:
            return None

        # Extract English description
        descriptions = cve.get("descriptions", [])
        desc_text = None
        for d in descriptions:
            if d.get("lang") == "en":
                desc_text = d.get("value")
                break
        if not desc_text and descriptions:
            desc_text = descriptions[0].get("value")

        cleaned_desc = clean_text(desc_text)
        if not cleaned_desc or len(cleaned_desc) < 10:
            return None

        # CVSS Severity
        metrics = cve.get("metrics", {})
        cvss_score, cvss_sev = self._extract_cvss(metrics)

        # Build informative title
        summary_snip = cleaned_desc[:80].rsplit(" ", 1)[0]
        if cvss_score is not None:
            title = f"{cve_id} (CVSS {cvss_score} {cvss_sev}): {summary_snip}"
        else:
            title = f"{cve_id}: {summary_snip}"

        canonical_url = f"https://nvd.nist.gov/vuln/detail/{cve_id}"
        published_at = parse_iso_or_rfc_date(cve.get("published")) or parse_iso_or_rfc_date(cve.get("lastModified"))
        source_identifier = cve.get("sourceIdentifier", "NVD")

        # Full description
        full_description = cleaned_desc
        if cvss_score is not None:
            full_description = f"[CVSS {cvss_score} {cvss_sev}] {cleaned_desc}"

        return Article(
            title=title,
            url=canonical_url,
            source="NVD",
            author=source_identifier,
            published_at=published_at,
            description=full_description,
            domain="Cybersecurity",
            raw_metadata={
                "cve_id": cve_id,
                "cvss_score": cvss_score,
                "cvss_severity": cvss_sev,
                "vuln_status": cve.get("vulnStatus"),
                "source_identifier": source_identifier,
            },
        )

    def fetch(
        self,
        domain: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Tuple[List[Article], Dict[str, Any]]:
        """Retrieves recent CVEs from the NVD API.

        Args:
            domain: Target domain filter (only returns articles if domain is Cybersecurity or None).
            limit: Maximum CVEs to return.

        Returns:
            Tuple[List[Article], Dict[str, Any]]: (articles, telemetry)
        """
        start_time = time.time()
        if not self.enabled:
            return [], {
                "status": "DISABLED",
                "count": 0,
                "error": None,
                "latency_seconds": 0.0,
            }

        # NVD only serves Cybersecurity
        if domain and domain.strip().lower() not in ("cybersecurity", "security"):
            return [], {
                "status": "SKIPPED_DOMAIN",
                "count": 0,
                "error": None,
                "latency_seconds": 0.0,
            }

        max_fetch = limit or self.results_per_page
        articles: List[Article] = []

        params = {
            "resultsPerPage": max_fetch,
        }

        try:
            logger.info(f"Fetching recent CVEs from NVD API (limit={max_fetch})")
            resp = self.session.get(self.base_url, params=params, timeout=self.timeout)
            if resp.status_code == 403 or resp.status_code == 429:
                err_msg = f"NVD API rate limit or authorization block (HTTP {resp.status_code})"
                logger.warning(err_msg)
                return [], {
                    "status": "RATE_LIMITED",
                    "count": 0,
                    "error": err_msg,
                    "latency_seconds": round(time.time() - start_time, 2),
                }

            resp.raise_for_status()
            data = resp.json()
            vuln_items = data.get("vulnerabilities", [])

            for item in vuln_items:
                art = self.parse_cve_item(item)
                if art:
                    articles.append(art)
                    if len(articles) >= max_fetch:
                        break

            latency = round(time.time() - start_time, 2)
            logger.info(f"NVD adapter successfully ingested {len(articles)} CVEs")

            return articles, {
                "status": "SUCCESS",
                "count": len(articles),
                "authenticated": bool(self.api_key),
                "error": None,
                "latency_seconds": latency,
            }
        except Exception as err:
            err_msg = f"NVD CVE API request failed: {err}"
            logger.warning(err_msg)
            return [], {
                "status": "FAILED",
                "count": 0,
                "error": err_msg,
                "latency_seconds": round(time.time() - start_time, 2),
            }
