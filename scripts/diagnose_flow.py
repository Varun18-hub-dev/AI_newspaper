"""Diagnostic script to trace every stage of the pipeline flow."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.ingestion.coordinator import MultiSourceDiscoveryCoordinator
from app.processing.article_processor import ArticleProcessor
from app.storage.service import StorageService
from app.storage.sqlite import SQLiteDatabase
from app.storage.publisher import EditionPublisher

def diagnose():
    print("=== [1] INSPECTING DATABASE & PREVIOUS STATE ===")
    db = SQLiteDatabase()
    stats = db.get_database_stats()
    print("Database stats:", stats)

    print("\n=== [2] DISCOVERY COORDINATOR ===")
    coord = MultiSourceDiscoveryCoordinator()
    raw_articles, statuses = coord.discover_all(domains=["ai", "technology"])
    print(f"Discovered raw articles: {len(raw_articles)}")
    for src, st in statuses.items():
        print(f"  {src}: {st}")

    print("\n=== [3] ARTICLE PROCESSOR - FILTERING & DEDUPLICATION ===")
    storage_service = StorageService(db=db)
    processor = ArticleProcessor(storage_service=storage_service)
    
    # Trace step 1 & 1.5
    from app.processing.filtering import filter_and_deduplicate
    filtered = filter_and_deduplicate(raw_articles)
    print(f"filter_and_deduplicate retained: {len(filtered)} articles")

    to_process, skipped, s_metrics = storage_service.check_and_register_articles(filtered)
    print(f"check_and_register_articles: to_process={len(to_process)}, skipped={len(skipped)}")
    print(f"  new_articles_persisted={s_metrics.new_articles_persisted}")
    print(f"  exact_duplicates_skipped={s_metrics.exact_duplicates_skipped}")
    print(f"  previously_seen_recognized={s_metrics.previously_seen_recognized}")

    print("\n=== [4] PRE-FILTER & RANKING ===")
    candidate_pairs = []
    rejected = []
    for art in (to_process if to_process else filtered[:20]):
        pf = processor.evaluate_pre_filter(art, None)
        if pf.should_send_to_llm:
            candidate_pairs.append((art, pf))
        else:
            rejected.append((art, pf))
    print(f"Candidate pairs passed pre-filter: {len(candidate_pairs)}, rejected: {len(rejected)}")
    if candidate_pairs:
        print(f"Sample candidate: '{candidate_pairs[0][0].title}' tier={candidate_pairs[0][1].tier} domain={candidate_pairs[0][0].domain}")
    if rejected:
        print(f"Sample rejected: '{rejected[0][0].title}' reason='{rejected[0][1].reason}' domain={rejected[0][0].domain}")

    print("\n=== [5] PUBLISHER INSPECTION ===")
    publisher = EditionPublisher()
    print(f"Publisher backend: {publisher.backend}")
    print(f"Publisher local_dir: {publisher.local_dir.resolve()}")
    ptr = publisher.get_current_pointer()
    print("Current edition pointer:", ptr)
    edition = publisher.get_current_edition()
    print("Current edition manifest:", edition.edition_id if edition else None)

if __name__ == "__main__":
    diagnose()
