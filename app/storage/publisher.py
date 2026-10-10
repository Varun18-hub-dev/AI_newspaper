"""Atomic publication engine and edition storage for Personalized AI Newspaper."""

from datetime import datetime, date
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import setup_logger

logger = setup_logger("edition_publisher")


class EditionStory(BaseModel):
    """Normalized story entry serialized in a published newspaper edition."""

    story_id: str = Field(..., description="Unique cluster or story identifier")
    title: str = Field(..., description="Story headline")
    url: str = Field(..., description="Canonical article URL")
    domain: str = Field(..., description="Category domain (e.g. AI, Technology)")
    topic: Optional[str] = Field(default=None, description="Classified subtopic")
    summary: str = Field(..., description="Agentic summary or validated excerpt")
    sources: List[str] = Field(default_factory=list, description="All publishing sources")
    published_at: Optional[str] = Field(default=None, description="Original publication timestamp ISO")
    first_seen_at: str = Field(..., description="Discovery timestamp ISO")
    relevance_score: float = Field(default=1.0, description="Evaluated relevance score")
    image_url: Optional[str] = Field(default=None, description="Featured image URL if available")
    raw_metadata: Dict[str, Any] = Field(default_factory=dict, description="Source-specific metadata")


class EditionManifest(BaseModel):
    """Immutable manifest representing a complete validated daily newspaper publication."""

    edition_id: str = Field(..., description="Unique edition identifier (e.g. edition_20261010_060000)")
    publication_date: str = Field(..., description="Publication calendar date (YYYY-MM-DD)")
    published_at: str = Field(..., description="Publication timestamp ISO")
    status: str = Field(default="PUBLISHED", description="Publication status (PUBLISHED, RETRACTED)")
    total_stories: int = Field(default=0, description="Total stories in this edition")
    domain_counts: Dict[str, int] = Field(default_factory=dict, description="Stories count per domain")
    sources_represented: List[str] = Field(default_factory=list, description="Unique publishing sources")
    run_id: str = Field(..., description="Pipeline execution run identifier")
    checksum: str = Field(..., description="SHA-256 integrity checksum of stories content")
    stories: List[EditionStory] = Field(default_factory=list, description="Curated stories in edition")


class CurrentEditionPointer(BaseModel):
    """Atomic pointer indicating the currently active live edition."""

    edition_id: str = Field(..., description="Currently active edition identifier")
    published_at: str = Field(..., description="Timestamp when edition was promoted live")
    checksum: str = Field(..., description="Checksum of active edition")
    total_stories: int = Field(default=0, description="Count of stories in current edition")
    run_id: str = Field(..., description="Run ID that generated this edition")


class EditionValidator:
    """Validates edition quality and data integrity before allowing promotion to live."""

    def __init__(
        self,
        min_stories: int = 3,
        min_domains: int = 1,
    ):
        self.min_stories = min_stories
        self.min_domains = min_domains

    def validate(self, stories: List[EditionStory]) -> Tuple[bool, Optional[str]]:
        """Validates stories against minimum publishing criteria.

        Args:
            stories: List of candidate EditionStory instances.

        Returns:
            Tuple[bool, Optional[str]]: (is_valid, failure_reason)
        """
        if not stories:
            return False, "Edition contains 0 stories."

        if len(stories) < self.min_stories:
            return False, f"Edition contains {len(stories)} stories, below minimum required threshold of {self.min_stories}."

        unique_domains = set(s.domain.lower() for s in stories if s.domain)
        if len(unique_domains) < self.min_domains:
            return False, f"Edition covers {len(unique_domains)} domains, below minimum {self.min_domains}."

        for i, s in enumerate(stories):
            if not s.title or len(s.title.strip()) < 5:
                return False, f"Story #{i} has an invalid or missing title."
            if not s.url or not (s.url.startswith("http://") or s.url.startswith("https://")):
                return False, f"Story #{i} has an invalid URL: {s.url}"
            if not s.summary or len(s.summary.strip()) < 10:
                return False, f"Story #{i} ('{s.title[:30]}') has an empty or insufficient summary."
            if not s.sources:
                return False, f"Story #{i} ('{s.title[:30]}') has no publishing sources attribution."

        return True, None


class EditionPublisher:
    """Manages atomic publication, durable storage, and retrieval of newspaper editions."""

    def __init__(
        self,
        storage_backend: Optional[str] = None,
        local_dir: Optional[str] = None,
        s3_bucket: Optional[str] = None,
        s3_client: Optional[Any] = None,
        validator: Optional[EditionValidator] = None,
    ):
        """Initializes the publisher.

        Args:
            storage_backend: 'local' or 's3' (defaults to settings.storage_backend).
            local_dir: Root directory for local edition storage (defaults to data/editions).
            s3_bucket: Target S3 bucket name (defaults to settings.s3_bucket_name).
            s3_client: Optional boto3 S3 client (injected or mocked).
            validator: EditionValidator instance.
        """
        self.backend = storage_backend or getattr(settings, "storage_backend", "local").lower()
        self.local_dir = Path(local_dir or getattr(settings, "editions_dir", "data/editions"))
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self.s3_bucket = s3_bucket or getattr(settings, "s3_bucket_name", None)
        self.s3_client = s3_client
        self.validator = validator or EditionValidator(
            min_stories=getattr(settings, "min_edition_stories", 3)
        )

    def _compute_checksum(self, stories_data: List[Dict[str, Any]]) -> str:
        """Computes deterministic SHA-256 digest of stories array."""
        serialized = json.dumps(stories_data, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def publish_edition(
        self,
        edition_id: str,
        stories: List[EditionStory],
        run_id: str,
    ) -> Tuple[bool, Optional[EditionManifest], Optional[str]]:
        """Validates and atomically publishes a new daily edition.

        If validation fails, the existing live edition pointer is preserved completely untouched.

        Args:
            edition_id: Unique edition identifier.
            stories: List of EditionStory items to publish.
            run_id: Associated pipeline run ID.

        Returns:
            Tuple[bool, Optional[EditionManifest], Optional[str]]: (success, manifest, error)
        """
        # 1. Quality Validation Gate
        valid, reason = self.validator.validate(stories)
        if not valid:
            logger.error(f"Edition publication validation failed for '{edition_id}': {reason}")
            return False, None, reason

        # 2. Build Manifest
        now = datetime.utcnow()
        pub_date = now.strftime("%Y-%m-%d")
        stories_dicts = [s.model_dump() for s in stories]
        checksum = self._compute_checksum(stories_dicts)

        domain_counts: Dict[str, int] = {}
        sources_set = set()
        for s in stories:
            d_norm = s.domain.strip()
            domain_counts[d_norm] = domain_counts.get(d_norm, 0) + 1
            for src in s.sources:
                sources_set.add(src)

        manifest = EditionManifest(
            edition_id=edition_id,
            publication_date=pub_date,
            published_at=now.isoformat(),
            status="PUBLISHED",
            total_stories=len(stories),
            domain_counts=domain_counts,
            sources_represented=sorted(list(sources_set)),
            run_id=run_id,
            checksum=checksum,
            stories=stories,
        )

        pointer = CurrentEditionPointer(
            edition_id=edition_id,
            published_at=manifest.published_at,
            checksum=checksum,
            total_stories=len(stories),
            run_id=run_id,
        )

        # 3. Store Edition Immuntably
        manifest_json = manifest.model_dump_json(indent=2)
        pointer_json = pointer.model_dump_json(indent=2)

        try:
            if self.backend == "s3" and self.s3_bucket:
                self._save_s3(f"editions/{edition_id}.json", manifest_json)
                # Atomically update current_edition pointer in S3
                self._save_s3("current_edition.json", pointer_json)
            else:
                # Local atomic file swap
                edition_path = self.local_dir / f"{edition_id}.json"
                temp_edition_path = self.local_dir / f"{edition_id}.tmp"
                temp_edition_path.write_text(manifest_json, encoding="utf-8")
                temp_edition_path.replace(edition_path)

                pointer_path = self.local_dir / "current_edition.json"
                temp_pointer_path = self.local_dir / "current_edition.tmp"
                temp_pointer_path.write_text(pointer_json, encoding="utf-8")
                temp_pointer_path.replace(pointer_path)

            logger.info(
                f"Successfully published edition '{edition_id}' with {len(stories)} stories "
                f"across {len(domain_counts)} domains (checksum: {checksum[:8]})."
            )
            return True, manifest, None
        except Exception as err:
            err_msg = f"Failed to persist edition artifacts: {err}"
            logger.error(err_msg)
            return False, None, err_msg

    def _save_s3(self, key: str, data: str) -> None:
        """Uploads payload to S3."""
        if not self.s3_client:
            import boto3
            self.s3_client = boto3.client("s3")
        self.s3_client.put_object(
            Bucket=self.s3_bucket,
            Key=key,
            Body=data.encode("utf-8"),
            ContentType="application/json",
        )

    def _read_s3(self, key: str) -> Optional[str]:
        """Reads payload from S3."""
        if not self.s3_client:
            import boto3
            self.s3_client = boto3.client("s3")
        try:
            resp = self.s3_client.get_object(Bucket=self.s3_bucket, Key=key)
            return resp["Body"].read().decode("utf-8")
        except Exception as e:
            logger.debug(f"S3 object '{key}' not found or error: {e}")
            return None

    def get_current_pointer(self) -> Optional[CurrentEditionPointer]:
        """Retrieves the current edition pointer."""
        try:
            if self.backend == "s3" and self.s3_bucket:
                data = self._read_s3("current_edition.json")
            else:
                p = self.local_dir / "current_edition.json"
                data = p.read_text(encoding="utf-8") if p.exists() else None

            if data:
                return CurrentEditionPointer.model_validate_json(data)
        except Exception as err:
            logger.warning(f"Could not read current edition pointer: {err}")
        return None

    def get_current_edition(self) -> Optional[EditionManifest]:
        """Retrieves the full manifest of the current live published edition."""
        pointer = self.get_current_pointer()
        if not pointer:
            return None
        return self.get_edition(pointer.edition_id)

    def get_edition(self, edition_id: str) -> Optional[EditionManifest]:
        """Retrieves a specific edition manifest by edition_id, verifying data integrity."""
        try:
            if self.backend == "s3" and self.s3_bucket:
                data = self._read_s3(f"editions/{edition_id}.json")
            else:
                p = self.local_dir / f"{edition_id}.json"
                data = p.read_text(encoding="utf-8") if p.exists() else None

            if data:
                manifest = EditionManifest.model_validate_json(data)
                # Verify payload integrity
                stories_dicts = [s.model_dump() for s in manifest.stories]
                calc_checksum = self._compute_checksum(stories_dicts)
                if manifest.checksum and calc_checksum != manifest.checksum:
                    logger.error(
                        f"Integrity check failed for edition '{edition_id}': "
                        f"manifest checksum {manifest.checksum} does not match computed {calc_checksum}"
                    )
                    return None
                return manifest
        except Exception as err:
            logger.warning(f"Could not read edition '{edition_id}': {err}")
        return None

    def list_editions(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Lists historical editions sorted newest first."""
        editions_meta: List[Dict[str, Any]] = []
        try:
            if self.backend == "s3" and self.s3_bucket:
                # S3 list objects
                if not self.s3_client:
                    import boto3
                    self.s3_client = boto3.client("s3")
                resp = self.s3_client.list_objects_v2(Bucket=self.s3_bucket, Prefix="editions/")
                for obj in resp.get("Contents", []):
                    key = obj.get("Key", "")
                    if key.endswith(".json"):
                        eid = key.split("/")[-1].replace(".json", "")
                        editions_meta.append({
                            "edition_id": eid,
                            "last_modified": obj.get("LastModified", "").isoformat() if hasattr(obj.get("LastModified", ""), "isoformat") else str(obj.get("LastModified")),
                        })
            else:
                for f in self.local_dir.glob("edition_*.json"):
                    editions_meta.append({
                        "edition_id": f.stem,
                        "file_path": str(f),
                        "modified_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    })
            editions_meta.sort(key=lambda x: x.get("edition_id", ""), reverse=True)
            return editions_meta[:limit]
        except Exception as err:
            logger.error(f"Failed to list editions: {err}")
            return []
