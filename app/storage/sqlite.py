"""SQLite persistence layer with versioned schema migrations, transactions, and indexing."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

from app.core.config import settings
from app.core.logging import setup_logger
from app.storage.models import (
    ArticleRecord,
    ClusterMemberRecord,
    PipelineRunRecord,
    StoryClusterRecord,
)

logger = setup_logger("sqlite_storage")

CURRENT_SCHEMA_VERSION = 2



def _parse_iso(val: Optional[str]) -> Optional[datetime]:
    """Safely parses ISO format datetime string into datetime object."""
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except Exception:
        return None


def _format_iso(dt: Optional[datetime]) -> Optional[str]:
    """Formats datetime object to standard ISO string."""
    if not dt:
        return None
    return dt.isoformat()


class SQLiteDatabase:
    """Manages SQLite connection, schema versioning, transactions, and queries."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        """Initializes database connection and applies migrations.

        Args:
            db_path: Path to SQLite database file or ':memory:' for in-memory testing.
                     Defaults to settings.db_path.
        """
        self.db_path_str = str(db_path if db_path is not None else settings.db_path)
        self.is_memory = self.db_path_str == ":memory:"

        if not self.is_memory:
            db_file = Path(self.db_path_str)
            db_file.parent.mkdir(parents=True, exist_ok=True)

        self._init_connection()
        self._apply_migrations()

    def _init_connection(self) -> None:
        """Initializes raw SQLite connection with proper pragma settings."""
        # For in-memory testing, keep single shared connection
        if self.is_memory:
            self._mem_conn = sqlite3.connect(
                ":memory:",
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            self._mem_conn.row_factory = sqlite3.Row
            self._mem_conn.execute("PRAGMA foreign_keys = ON;")
        else:
            self._mem_conn = None

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provides a managed connection within a transactional block."""
        if self.is_memory:
            conn = self._mem_conn
            with conn:
                yield conn
        else:
            conn = sqlite3.connect(
                self.db_path_str,
                check_same_thread=False,
                timeout=30.0,
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            try:
                with conn:
                    yield conn
            finally:
                conn.close()

    def _apply_migrations(self) -> None:
        """Applies schema migrations idempotently up to CURRENT_SCHEMA_VERSION."""
        with self.get_connection() as conn:
            # 1. Schema version table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMP NOT NULL,
                    description TEXT NOT NULL
                );
                """
            )

            cur = conn.execute("SELECT MAX(version) FROM schema_version;")
            row = cur.fetchone()
            current_v = row[0] if (row and row[0] is not None) else 0

            if current_v < 1:
                logger.info("Applying migration v1: Creating initial newspaper schema...")
                self._migrate_v1(conn)
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?);",
                    (1, datetime.utcnow().isoformat(), "Initial Phase 5 persistent tables"),
                )

            if current_v < 2:
                logger.info("Applying migration v2: Creating pipeline_runs table...")
                self._migrate_v2(conn)
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?);",
                    (2, datetime.utcnow().isoformat(), "Phase 7 pipeline_runs table"),
                )

    def _migrate_v2(self, conn: sqlite3.Connection) -> None:
        """Version 2 schema: pipeline_runs table and indexes."""
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id TEXT PRIMARY KEY,
                trigger_type TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                duration_seconds REAL,
                status TEXT NOT NULL,
                articles_discovered INTEGER NOT NULL DEFAULT 0,
                articles_deduplicated INTEGER NOT NULL DEFAULT 0,
                articles_prefiltered INTEGER NOT NULL DEFAULT 0,
                clusters_formed INTEGER NOT NULL DEFAULT 0,
                qwen_evaluations INTEGER NOT NULL DEFAULT 0,
                articles_stored INTEGER NOT NULL DEFAULT 0,
                domain_counts TEXT,
                feed_errors TEXT,
                error_message TEXT,
                run_metadata TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started ON pipeline_runs(started_at);
            CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status);
            CREATE INDEX IF NOT EXISTS idx_pipeline_runs_trigger ON pipeline_runs(trigger_type);
            """
        )

    def _migrate_v1(self, conn: sqlite3.Connection) -> None:
        """Version 1 schema: articles, story_clusters, cluster_members with indexes."""
        conn.executescript(
            """
            -- Articles table
            CREATE TABLE IF NOT EXISTS articles (
                id TEXT PRIMARY KEY,
                canonical_url TEXT NOT NULL UNIQUE,
                original_url TEXT NOT NULL,
                normalized_title TEXT NOT NULL,
                source TEXT NOT NULL,
                author TEXT,
                published_at TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                content_fingerprint TEXT,
                cluster_id TEXT,
                processing_status TEXT NOT NULL DEFAULT 'PENDING',
                relevance_score REAL,
                topic TEXT,
                domain TEXT NOT NULL DEFAULT 'AI',
                extra_metadata TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_articles_canonical_url ON articles(canonical_url);
            CREATE INDEX IF NOT EXISTS idx_articles_fingerprint ON articles(content_fingerprint);
            CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(processing_status);
            CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at);
            CREATE INDEX IF NOT EXISTS idx_articles_cluster_id ON articles(cluster_id);
            CREATE INDEX IF NOT EXISTS idx_articles_title_source ON articles(normalized_title, source);

            -- Story clusters table
            CREATE TABLE IF NOT EXISTS story_clusters (
                id TEXT PRIMARY KEY,
                representative_article_id TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_processed_at TEXT NOT NULL,
                story_fingerprint TEXT,
                lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE',
                source_count INTEGER NOT NULL DEFAULT 1,
                sources TEXT NOT NULL,
                topic TEXT,
                domain TEXT NOT NULL DEFAULT 'AI',
                extra_metadata TEXT,
                FOREIGN KEY (representative_article_id) REFERENCES articles(id)
            );

            CREATE INDEX IF NOT EXISTS idx_clusters_first_seen ON story_clusters(first_seen_at);
            CREATE INDEX IF NOT EXISTS idx_clusters_last_seen ON story_clusters(last_seen_at);
            CREATE INDEX IF NOT EXISTS idx_clusters_lifecycle ON story_clusters(lifecycle_status);

            -- Cluster members table
            CREATE TABLE IF NOT EXISTS cluster_members (
                cluster_id TEXT NOT NULL,
                article_id TEXT NOT NULL,
                is_representative INTEGER NOT NULL DEFAULT 0,
                added_at TEXT NOT NULL,
                is_meaningful_update INTEGER NOT NULL DEFAULT 0,
                update_reason TEXT,
                PRIMARY KEY (cluster_id, article_id),
                FOREIGN KEY (cluster_id) REFERENCES story_clusters(id) ON DELETE CASCADE,
                FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_cluster_members_article ON cluster_members(article_id);
            """
        )

    def get_schema_version(self) -> int:
        """Returns the current applied schema version."""
        with self.get_connection() as conn:
            cur = conn.execute("SELECT MAX(version) FROM schema_version;")
            row = cur.fetchone()
            return row[0] if (row and row[0] is not None) else 0

    # =========================================================================
    # Article Operations
    # =========================================================================
    def _row_to_article_record(self, row: sqlite3.Row) -> ArticleRecord:
        """Converts database Row to ArticleRecord."""
        extra_meta = {}
        if row["extra_metadata"]:
            try:
                extra_meta = json.loads(row["extra_metadata"])
            except Exception:
                pass

        return ArticleRecord(
            id=row["id"],
            canonical_url=row["canonical_url"],
            original_url=row["original_url"],
            normalized_title=row["normalized_title"],
            source=row["source"],
            author=row["author"],
            published_at=_parse_iso(row["published_at"]),
            first_seen_at=_parse_iso(row["first_seen_at"]) or datetime.utcnow(),
            last_seen_at=_parse_iso(row["last_seen_at"]) or datetime.utcnow(),
            content_fingerprint=row["content_fingerprint"],
            cluster_id=row["cluster_id"],
            processing_status=row["processing_status"],
            relevance_score=row["relevance_score"],
            topic=row["topic"],
            domain=row["domain"],
            extra_metadata=extra_meta,
        )

    def get_article_by_id(self, article_id: str) -> Optional[ArticleRecord]:
        """Retrieves article record by internal ID."""
        with self.get_connection() as conn:
            cur = conn.execute("SELECT * FROM articles WHERE id = ?;", (article_id,))
            row = cur.fetchone()
            return self._row_to_article_record(row) if row else None

    def get_article_by_canonical_url(self, canonical_url: str) -> Optional[ArticleRecord]:
        """Retrieves article record by canonical URL."""
        with self.get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM articles WHERE canonical_url = ?;",
                (canonical_url.strip(),),
            )
            row = cur.fetchone()
            return self._row_to_article_record(row) if row else None

    def get_article_by_fingerprint(self, fingerprint: str) -> Optional[ArticleRecord]:
        """Retrieves an article record by content fingerprint if non-empty."""
        if not fingerprint:
            return None
        with self.get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM articles WHERE content_fingerprint = ? LIMIT 1;",
                (fingerprint,),
            )
            row = cur.fetchone()
            return self._row_to_article_record(row) if row else None

    def get_article_by_title_and_source(
        self, title: str, source: str
    ) -> Optional[ArticleRecord]:
        """Retrieves an article by exact title and source match."""
        with self.get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM articles WHERE normalized_title = ? AND source = ? LIMIT 1;",
                (title.strip(), source.strip()),
            )
            row = cur.fetchone()
            return self._row_to_article_record(row) if row else None

    def insert_article(self, article: ArticleRecord) -> bool:
        """Inserts a new article record. Returns True on success, False if already exists."""
        try:
            with self.get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO articles (
                        id, canonical_url, original_url, normalized_title, source,
                        author, published_at, first_seen_at, last_seen_at,
                        content_fingerprint, cluster_id, processing_status,
                        relevance_score, topic, domain, extra_metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        article.id,
                        article.canonical_url,
                        article.original_url,
                        article.normalized_title,
                        article.source,
                        article.author,
                        _format_iso(article.published_at),
                        _format_iso(article.first_seen_at),
                        _format_iso(article.last_seen_at),
                        article.content_fingerprint,
                        article.cluster_id,
                        article.processing_status,
                        article.relevance_score,
                        article.topic,
                        article.domain,
                        json.dumps(article.extra_metadata or {}),
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            logger.error(f"Error inserting article '{article.canonical_url}': {e}")
            raise

    def update_article_seen(self, article_id: str, last_seen: datetime) -> None:
        """Refreshes last_seen_at timestamp for an already recorded article."""
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE articles SET last_seen_at = ? WHERE id = ?;",
                (_format_iso(last_seen), article_id),
            )

    def update_article_status(
        self,
        article_id: str,
        status: str,
        relevance_score: Optional[float] = None,
        topic: Optional[str] = None,
        cluster_id: Optional[str] = None,
        content_fingerprint: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> None:
        """Updates processing status, scores, topic, cluster assignment, and optional agent summary."""
        with self.get_connection() as conn:
            if summary:
                conn.execute(
                    """
                    UPDATE articles
                    SET processing_status = ?,
                        relevance_score = COALESCE(?, relevance_score),
                        topic = COALESCE(?, topic),
                        cluster_id = COALESCE(?, cluster_id),
                        content_fingerprint = COALESCE(?, content_fingerprint),
                        extra_metadata = json_set(COALESCE(extra_metadata, '{}'), '$.agent_summary', ?)
                    WHERE id = ?;
                    """,
                    (status, relevance_score, topic, cluster_id, content_fingerprint, summary, article_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE articles
                    SET processing_status = ?,
                        relevance_score = COALESCE(?, relevance_score),
                        topic = COALESCE(?, topic),
                        cluster_id = COALESCE(?, cluster_id),
                        content_fingerprint = COALESCE(?, content_fingerprint)
                    WHERE id = ?;
                    """,
                    (status, relevance_score, topic, cluster_id, content_fingerprint, article_id),
                )

    # =========================================================================
    # Story Cluster Operations
    # =========================================================================
    def _row_to_cluster_record(self, row: sqlite3.Row) -> StoryClusterRecord:
        """Converts database Row to StoryClusterRecord."""
        sources = []
        if row["sources"]:
            try:
                sources = json.loads(row["sources"])
            except Exception:
                sources = [s.strip() for s in row["sources"].split(",") if s.strip()]

        extra_meta = {}
        if row["extra_metadata"]:
            try:
                extra_meta = json.loads(row["extra_metadata"])
            except Exception:
                pass

        return StoryClusterRecord(
            id=row["id"],
            representative_article_id=row["representative_article_id"],
            first_seen_at=_parse_iso(row["first_seen_at"]) or datetime.utcnow(),
            last_seen_at=_parse_iso(row["last_seen_at"]) or datetime.utcnow(),
            last_processed_at=_parse_iso(row["last_processed_at"]) or datetime.utcnow(),
            story_fingerprint=row["story_fingerprint"],
            lifecycle_status=row["lifecycle_status"],
            source_count=row["source_count"],
            sources=sources,
            topic=row["topic"],
            domain=row["domain"],
            extra_metadata=extra_meta,
        )

    def get_cluster_by_id(self, cluster_id: str) -> Optional[StoryClusterRecord]:
        """Retrieves story cluster by ID."""
        with self.get_connection() as conn:
            cur = conn.execute("SELECT * FROM story_clusters WHERE id = ?;", (cluster_id,))
            row = cur.fetchone()
            return self._row_to_cluster_record(row) if row else None

    def get_active_clusters_in_window(
        self, since: datetime, domain: str = "AI"
    ) -> List[StoryClusterRecord]:
        """Retrieves active story clusters observed since specified cutoff timestamp."""
        iso_cutoff = _format_iso(since)
        with self.get_connection() as conn:
            cur = conn.execute(
                """
                SELECT * FROM story_clusters
                WHERE domain = ? AND last_seen_at >= ? AND lifecycle_status != 'ARCHIVED'
                ORDER BY last_seen_at DESC;
                """,
                (domain, iso_cutoff),
            )
            return [self._row_to_cluster_record(row) for row in cur.fetchall()]

    def upsert_cluster(self, cluster: StoryClusterRecord) -> None:
        """Inserts or updates a story cluster record."""
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO story_clusters (
                    id, representative_article_id, first_seen_at, last_seen_at,
                    last_processed_at, story_fingerprint, lifecycle_status,
                    source_count, sources, topic, domain, extra_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    representative_article_id = excluded.representative_article_id,
                    last_seen_at = excluded.last_seen_at,
                    last_processed_at = excluded.last_processed_at,
                    story_fingerprint = COALESCE(excluded.story_fingerprint, story_clusters.story_fingerprint),
                    lifecycle_status = excluded.lifecycle_status,
                    source_count = excluded.source_count,
                    sources = excluded.sources,
                    topic = COALESCE(excluded.topic, story_clusters.topic),
                    extra_metadata = excluded.extra_metadata;
                """,
                (
                    cluster.id,
                    cluster.representative_article_id,
                    _format_iso(cluster.first_seen_at),
                    _format_iso(cluster.last_seen_at),
                    _format_iso(cluster.last_processed_at),
                    cluster.story_fingerprint,
                    cluster.lifecycle_status,
                    cluster.source_count,
                    json.dumps(cluster.sources),
                    cluster.topic,
                    cluster.domain,
                    json.dumps(cluster.extra_metadata or {}),
                ),
            )

    def add_cluster_member(
        self,
        cluster_id: str,
        article_id: str,
        is_representative: bool = False,
        is_meaningful_update: bool = False,
        update_reason: Optional[str] = None,
        added_at: Optional[datetime] = None,
    ) -> None:
        """Associates an article as a member of a story cluster."""
        ts = added_at or datetime.utcnow()
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO cluster_members (
                    cluster_id, article_id, is_representative, added_at,
                    is_meaningful_update, update_reason
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(cluster_id, article_id) DO UPDATE SET
                    is_representative = excluded.is_representative,
                    is_meaningful_update = excluded.is_meaningful_update,
                    update_reason = excluded.update_reason;
                """,
                (
                    cluster_id,
                    article_id,
                    1 if is_representative else 0,
                    _format_iso(ts),
                    1 if is_meaningful_update else 0,
                    update_reason,
                ),
            )
            # Also update article cluster_id pointer
            conn.execute(
                "UPDATE articles SET cluster_id = ? WHERE id = ?;",
                (cluster_id, article_id),
            )

    def get_cluster_member_articles(self, cluster_id: str) -> List[ArticleRecord]:
        """Retrieves all member article records for a given cluster."""
        with self.get_connection() as conn:
            cur = conn.execute(
                """
                SELECT a.* FROM articles a
                JOIN cluster_members cm ON a.id = cm.article_id
                WHERE cm.cluster_id = ?
                ORDER BY a.published_at ASC, a.first_seen_at ASC;
                """,
                (cluster_id,),
            )
            return [self._row_to_article_record(row) for row in cur.fetchall()]

    # =========================================================================
    # Observability & Diagnostics
    # =========================================================================
    def get_database_stats(self) -> Dict[str, Any]:
        """Returns row counts and database disk size in bytes."""
        size_bytes = 0
        if not self.is_memory and Path(self.db_path_str).exists():
            size_bytes = Path(self.db_path_str).stat().st_size

        with self.get_connection() as conn:
            art_count = conn.execute("SELECT COUNT(*) FROM articles;").fetchone()[0]
            cluster_count = conn.execute("SELECT COUNT(*) FROM story_clusters;").fetchone()[0]
            member_count = conn.execute("SELECT COUNT(*) FROM cluster_members;").fetchone()[0]
            classified_count = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE processing_status LIKE 'CLASSIFIED%';",
            ).fetchone()[0]
            run_count = conn.execute("SELECT COUNT(*) FROM pipeline_runs;").fetchone()[0]

        return {
            "db_path": self.db_path_str,
            "db_size_bytes": size_bytes,
            "total_articles": art_count,
            "total_story_clusters": cluster_count,
            "total_cluster_members": member_count,
            "classified_articles": classified_count,
            "total_pipeline_runs": run_count,
        }

    # =========================================================================
    # Pipeline Run Operations (Phase 7)
    # =========================================================================
    def _row_to_pipeline_run_record(self, row: sqlite3.Row) -> PipelineRunRecord:
        """Converts database Row to PipelineRunRecord."""
        domain_counts = {}
        if row["domain_counts"]:
            try:
                domain_counts = json.loads(row["domain_counts"])
            except Exception:
                pass

        feed_errors = []
        if row["feed_errors"]:
            try:
                feed_errors = json.loads(row["feed_errors"])
            except Exception:
                pass

        run_meta = {}
        if row["run_metadata"]:
            try:
                run_meta = json.loads(row["run_metadata"])
            except Exception:
                pass

        return PipelineRunRecord(
            id=row["id"],
            trigger_type=row["trigger_type"],
            started_at=_parse_iso(row["started_at"]) or datetime.utcnow(),
            completed_at=_parse_iso(row["completed_at"]),
            duration_seconds=row["duration_seconds"],
            status=row["status"],
            articles_discovered=row["articles_discovered"],
            articles_deduplicated=row["articles_deduplicated"],
            articles_prefiltered=row["articles_prefiltered"],
            clusters_formed=row["clusters_formed"],
            qwen_evaluations=row["qwen_evaluations"],
            articles_stored=row["articles_stored"],
            domain_counts=domain_counts,
            feed_errors=feed_errors,
            error_message=row["error_message"],
            run_metadata=run_meta,
        )

    def insert_run(self, record: PipelineRunRecord) -> None:
        """Inserts a new pipeline run record into the database."""
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO pipeline_runs (
                    id, trigger_type, started_at, completed_at, duration_seconds,
                    status, articles_discovered, articles_deduplicated,
                    articles_prefiltered, clusters_formed, qwen_evaluations,
                    articles_stored, domain_counts, feed_errors, error_message,
                    run_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    record.id,
                    record.trigger_type,
                    _format_iso(record.started_at),
                    _format_iso(record.completed_at),
                    record.duration_seconds,
                    record.status,
                    record.articles_discovered,
                    record.articles_deduplicated,
                    record.articles_prefiltered,
                    record.clusters_formed,
                    record.qwen_evaluations,
                    record.articles_stored,
                    json.dumps(record.domain_counts),
                    json.dumps(record.feed_errors),
                    record.error_message,
                    json.dumps(record.run_metadata),
                ),
            )

    def update_run(self, record: PipelineRunRecord) -> None:
        """Updates an existing pipeline run record."""
        with self.get_connection() as conn:
            conn.execute(
                """
                UPDATE pipeline_runs SET
                    trigger_type = ?,
                    completed_at = ?,
                    duration_seconds = ?,
                    status = ?,
                    articles_discovered = ?,
                    articles_deduplicated = ?,
                    articles_prefiltered = ?,
                    clusters_formed = ?,
                    qwen_evaluations = ?,
                    articles_stored = ?,
                    domain_counts = ?,
                    feed_errors = ?,
                    error_message = ?,
                    run_metadata = ?
                WHERE id = ?;
                """,
                (
                    record.trigger_type,
                    _format_iso(record.completed_at),
                    record.duration_seconds,
                    record.status,
                    record.articles_discovered,
                    record.articles_deduplicated,
                    record.articles_prefiltered,
                    record.clusters_formed,
                    record.qwen_evaluations,
                    record.articles_stored,
                    json.dumps(record.domain_counts),
                    json.dumps(record.feed_errors),
                    record.error_message,
                    json.dumps(record.run_metadata),
                    record.id,
                ),
            )

    def get_run_by_id(self, run_id: str) -> Optional[PipelineRunRecord]:
        """Retrieves a pipeline run by its unique identifier."""
        with self.get_connection() as conn:
            cur = conn.execute("SELECT * FROM pipeline_runs WHERE id = ?;", (run_id,))
            row = cur.fetchone()
            return self._row_to_pipeline_run_record(row) if row else None

    def get_recent_runs(self, limit: int = 10) -> List[PipelineRunRecord]:
        """Retrieves the most recent pipeline runs ordered by started_at descending."""
        with self.get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT ?;",
                (limit,),
            )
            return [self._row_to_pipeline_run_record(row) for row in cur.fetchall()]

    def get_last_successful_run(
        self, trigger_type: Optional[str] = None
    ) -> Optional[PipelineRunRecord]:
        """Retrieves the most recent successful or partially successful pipeline run.

        Args:
            trigger_type: If provided, filters by trigger_type (e.g., 'SCHEDULED' or 'MANUAL').

        Returns:
            Optional[PipelineRunRecord]: Last successful run, or None.
        """
        with self.get_connection() as conn:
            if trigger_type:
                cur = conn.execute(
                    """
                    SELECT * FROM pipeline_runs
                    WHERE status IN ('SUCCESS', 'PARTIAL_SUCCESS') AND trigger_type = ?
                    ORDER BY started_at DESC LIMIT 1;
                    """,
                    (trigger_type,),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT * FROM pipeline_runs
                    WHERE status IN ('SUCCESS', 'PARTIAL_SUCCESS')
                    ORDER BY started_at DESC LIMIT 1;
                    """
                )
            row = cur.fetchone()
            return self._row_to_pipeline_run_record(row) if row else None

    def cleanup_interrupted_runs(self, active_run_id: Optional[str] = None) -> int:
        """Finds any runs left in 'RUNNING' status from crashed or aborted processes and marks them FAILED.

        Args:
            active_run_id: Optional ID of currently active run to exclude from cleanup.

        Returns:
            int: Number of stale running records marked FAILED.
        """
        with self.get_connection() as conn:
            if active_run_id:
                cur = conn.execute(
                    """
                    UPDATE pipeline_runs
                    SET status = 'FAILED',
                        completed_at = COALESCE(completed_at, ?),
                        error_message = 'Interrupted: Process terminated abruptly before completion'
                    WHERE status = 'RUNNING' AND id != ?;
                    """,
                    (datetime.utcnow().isoformat(), active_run_id),
                )
            else:
                cur = conn.execute(
                    """
                    UPDATE pipeline_runs
                    SET status = 'FAILED',
                        completed_at = COALESCE(completed_at, ?),
                        error_message = 'Interrupted: Process terminated abruptly before completion'
                    WHERE status = 'RUNNING';
                    """,
                    (datetime.utcnow().isoformat(),),
                )
            return cur.rowcount

    # =========================================================================
    # Newspaper Web API Queries (Phase 8)
    # =========================================================================
    def get_newspaper_stories(
        self,
        domain: Optional[str] = None,
        topic: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Queries story clusters joined with their representative articles for newspaper display.

        Args:
            domain: Optional domain filter (e.g. 'ai', 'technology').
            topic: Optional topic filter.
            page: 1-indexed page number.
            page_size: Number of items per page.

        Returns:
            Tuple[List[Dict[str, Any]], int]: (List of story dictionaries, total matching count).
        """
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size

        where_clauses = ["sc.lifecycle_status != 'ARCHIVED'"]
        params: List[Any] = []

        if domain:
            where_clauses.append("LOWER(sc.domain) = LOWER(?)")
            params.append(domain.strip())

        if topic:
            where_clauses.append("LOWER(COALESCE(sc.topic, '')) = LOWER(?)")
            params.append(topic.strip())

        where_sql = " AND ".join(where_clauses)

        with self.get_connection() as conn:
            # 1. Total count
            count_sql = f"SELECT COUNT(*) FROM story_clusters sc WHERE {where_sql};"
            total = conn.execute(count_sql, params).fetchone()[0]

            # 2. Paginated rows
            query_sql = f"""
                SELECT
                    sc.id AS cluster_id,
                    sc.domain,
                    COALESCE(sc.topic, a.topic, 'General') AS topic,
                    sc.source_count,
                    sc.sources,
                    sc.first_seen_at,
                    sc.last_seen_at,
                    a.id AS article_id,
                    a.normalized_title AS headline,
                    COALESCE(
                        json_extract(a.extra_metadata, '$.agent_summary'),
                        json_extract(a.extra_metadata, '$.extracted_excerpt'),
                        json_extract(a.extra_metadata, '$.description'),
                        ''
                    ) AS summary,
                    json_extract(a.extra_metadata, '$.image_url') AS image_url,
                    a.source AS representative_source,
                    a.original_url AS representative_url,
                    a.published_at,
                    a.relevance_score,
                    (
                        SELECT COUNT(*) FROM cluster_members cm WHERE cm.cluster_id = sc.id
                    ) AS member_count,
                    (
                        SELECT MAX(cm.is_meaningful_update) FROM cluster_members cm WHERE cm.cluster_id = sc.id
                    ) AS has_updates,
                    (
                        SELECT cm.update_reason FROM cluster_members cm
                        WHERE cm.cluster_id = sc.id AND cm.is_meaningful_update = 1
                        ORDER BY cm.added_at DESC LIMIT 1
                    ) AS update_reason
                FROM story_clusters sc
                LEFT JOIN articles a ON sc.representative_article_id = a.id
                WHERE {where_sql}
                ORDER BY sc.last_seen_at DESC
                LIMIT ? OFFSET ?;
            """
            cur = conn.execute(query_sql, params + [page_size, offset])
            rows = cur.fetchall()

            stories: List[Dict[str, Any]] = []
            for r in rows:
                sources_list = []
                if r["sources"]:
                    try:
                        sources_list = json.loads(r["sources"])
                    except Exception:
                        sources_list = [s.strip() for s in r["sources"].split(",") if s.strip()]

                stories.append({
                    "cluster_id": r["cluster_id"],
                    "headline": r["headline"] or "Untitled Story",
                    "summary": r["summary"] or None,
                    "domain": r["domain"],
                    "topic": r["topic"],
                    "published_at": r["published_at"],
                    "first_seen_at": r["first_seen_at"],
                    "last_seen_at": r["last_seen_at"],
                    "representative_source": r["representative_source"] or "Unknown",
                    "representative_url": r["representative_url"] or "",
                    "source_count": r["source_count"] or 1,
                    "sources": sources_list,
                    "has_updates": bool(r["has_updates"]),
                    "update_reason": r["update_reason"],
                    "relevance_score": r["relevance_score"],
                    "member_count": r["member_count"] or 1,
                    "image_url": r["image_url"] or None,
                })

            return stories, total

    def get_story_detail(self, cluster_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a story cluster, its representative article, and all member articles."""
        cluster = self.get_cluster_by_id(cluster_id)
        if not cluster:
            return None

        rep_art = self.get_article_by_id(cluster.representative_article_id)

        with self.get_connection() as conn:
            cur = conn.execute(
                """
                SELECT
                    a.id AS article_id,
                    a.normalized_title AS title,
                    a.original_url AS url,
                    a.canonical_url,
                    a.source,
                    a.author,
                    a.published_at,
                    a.domain,
                    a.topic,
                    a.relevance_score,
                    cm.is_representative,
                    cm.is_meaningful_update,
                    cm.update_reason,
                    cm.added_at,
                    COALESCE(
                        json_extract(a.extra_metadata, '$.extracted_excerpt'),
                        json_extract(a.extra_metadata, '$.description'),
                        ''
                    ) AS excerpt
                FROM cluster_members cm
                JOIN articles a ON cm.article_id = a.id
                WHERE cm.cluster_id = ?
                ORDER BY cm.is_representative DESC, a.published_at DESC;
                """,
                (cluster_id,),
            )
            member_rows = cur.fetchall()

        members = [
            {
                "article_id": m["article_id"],
                "title": m["title"],
                "url": m["url"],
                "canonical_url": m["canonical_url"],
                "source": m["source"],
                "author": m["author"],
                "published_at": m["published_at"],
                "domain": m["domain"],
                "topic": m["topic"],
                "relevance_score": m["relevance_score"],
                "is_representative": bool(m["is_representative"]),
                "is_meaningful_update": bool(m["is_meaningful_update"]),
                "update_reason": m["update_reason"],
                "added_at": m["added_at"],
                "excerpt": m["excerpt"] or None,
            }
            for m in member_rows
        ]

        headline = rep_art.normalized_title if rep_art else "Untitled Story"
        summary = None
        if rep_art and rep_art.extra_metadata:
            summary = (
                rep_art.extra_metadata.get("agent_summary")
                or rep_art.extra_metadata.get("extracted_excerpt")
                or rep_art.extra_metadata.get("description")
            )

        return {
            "cluster_id": cluster.id,
            "headline": headline,
            "summary": summary,
            "domain": cluster.domain,
            "topic": cluster.topic or (rep_art.topic if rep_art else "General"),
            "published_at": _format_iso(rep_art.published_at) if rep_art else None,
            "first_seen_at": _format_iso(cluster.first_seen_at),
            "last_seen_at": _format_iso(cluster.last_seen_at),
            "representative_source": rep_art.source if rep_art else "Unknown",
            "representative_url": rep_art.original_url if rep_art else "",
            "source_count": cluster.source_count,
            "sources": cluster.sources,
            "lifecycle_status": cluster.lifecycle_status,
            "members": members,
        }

    def get_domain_and_topic_counts(self) -> Dict[str, Any]:
        """Calculates story cluster and article counts grouped by domain."""
        with self.get_connection() as conn:
            # Cluster counts by domain
            c_rows = conn.execute(
                """
                SELECT domain, COUNT(*) AS count
                FROM story_clusters
                WHERE lifecycle_status != 'ARCHIVED'
                GROUP BY domain;
                """
            ).fetchall()
            cluster_counts = {r["domain"].lower(): r["count"] for r in c_rows}

            # Article counts by domain
            a_rows = conn.execute(
                """
                SELECT domain, COUNT(*) AS count
                FROM articles
                GROUP BY domain;
                """
            ).fetchall()
            article_counts = {r["domain"].lower(): r["count"] for r in a_rows}

            # Distinct topics per domain
            t_rows = conn.execute(
                """
                SELECT domain, topic, COUNT(*) as count
                FROM story_clusters
                WHERE topic IS NOT NULL AND topic != ''
                GROUP BY domain, topic;
                """
            ).fetchall()
            topics_by_domain: Dict[str, List[str]] = {}
            for tr in t_rows:
                d = tr["domain"].lower()
                if d not in topics_by_domain:
                    topics_by_domain[d] = []
                topics_by_domain[d].append(tr["topic"])

        return {
            "cluster_counts": cluster_counts,
            "article_counts": article_counts,
            "topics_by_domain": topics_by_domain,
        }



