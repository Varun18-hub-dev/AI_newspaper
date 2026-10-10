"""HTTP webpage fetcher for article content extraction."""

from typing import Optional, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from app.core.logging import setup_logger

logger = setup_logger("web_fetcher")


class WebPageFetcher:
    """Fetches HTML webpage content resiliently with session pooling and retry backoff."""

    def __init__(
        self,
        timeout: float = 5.0,
        user_agent: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 AI-Newspaper/1.0"
        ),
        max_retries: int = 1,
    ):
        """Initializes the fetcher.

        Args:
            timeout: HTTP request timeout in seconds.
            user_agent: Custom User-Agent string.
            max_retries: Maximum automatic retries on transient errors.
        """
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_retries = max_retries
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def fetch_html(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """Fetches raw HTML string from target URL.

        Args:
            url: The webpage URL to fetch.

        Returns:
            Tuple[Optional[str], Optional[str]]: (html_content, error_message)
        """
        if not url or not url.strip():
            return None, "Empty URL provided"

        logger.debug(f"Fetching webpage HTML: {url}")
        try:
            response = self.session.get(
                url.strip(),
                timeout=self.timeout,
                allow_redirects=True,
            )
            response.raise_for_status()

            # Ensure text content
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" not in content_type and "application/xhtml" not in content_type and "text/plain" not in content_type:
                logger.debug(f"Non-HTML content type for {url}: {content_type}")

            return response.text, None
        except requests.exceptions.Timeout as err:
            logger.warning(f"Timeout fetching {url}: {err}")
            return None, f"Request timed out after {self.timeout}s"
        except requests.exceptions.HTTPError as err:
            logger.warning(f"HTTP error fetching {url}: {err}")
            return None, f"HTTP status error: {err}"
        except requests.exceptions.ConnectionError as err:
            logger.warning(f"Connection error fetching {url}: {err}")
            return None, f"Connection failed: {err}"
        except requests.exceptions.RequestException as err:
            logger.warning(f"Request exception fetching {url}: {err}")
            return None, f"Request error: {err}"
        except Exception as err:
            logger.warning(f"Unexpected error fetching {url}: {err}")
            return None, f"Unexpected error: {err}"
