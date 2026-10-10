"""Diagnose why the Phase 6 smoke test produced 45 candidates and 45 clusters."""

import sys
from pathlib import Path
import numpy as np

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.ingestion.rss import RSSConnector
from app.domains.registry import get_domain_registry
from app.processing.filtering import filter_and_deduplicate
from app.clustering import StoryClusterer, EntityGuard

def main():
    connector = RSSConnector(max_items_per_feed=3)
    all_articles, statuses = connector.fetch_all_domains()
    filtered = filter_and_deduplicate(all_articles)
    print(f"Fetched {len(all_articles)} total, {len(filtered)} deduplicated unique articles.")

    clusterer = StoryClusterer()
    guard = EntityGuard()

    print(f"\nClusterer similarity threshold: {clusterer.similarity_threshold}")
    print("\n--- Pairwise similarity analysis within domains ---")
    
    for domain in ["AI", "Technology", "Science", "Cybersecurity", "Business and startups"]:
        dom_articles = [a for a in filtered if a.domain == domain]
        print(f"\nDomain: {domain} ({len(dom_articles)} articles)")
        if len(dom_articles) < 2:
            continue
        texts = [a.title + " " + (a.description or "") for a in dom_articles]
        sims = clusterer.embedding_provider.compute_similarity_matrix(texts)
        np.fill_diagonal(sims, -1.0)
        max_idx = np.unravel_index(np.argmax(sims), sims.shape)
        i, j = max_idx
        max_sim = sims[i, j]
        a1, a2 = dom_articles[i], dom_articles[j]
        guard_allowed, reason = guard.is_merge_allowed(a1, a2)
        print(f"  Highest similarity pair: {max_sim:.4f}")
        print(f"    Art 1: [{a1.source}] {a1.title}")
        print(f"    Art 2: [{a2.source}] {a2.title}")
        print(f"    EntityGuard allowed? {guard_allowed} (Reason: {reason})")
        
        above_thresh = []
        for r in range(len(dom_articles)):
            for c in range(r + 1, len(dom_articles)):
                if sims[r, c] >= 0.50:
                    above_thresh.append((sims[r, c], dom_articles[r], dom_articles[c]))
        
        if above_thresh:
            print(f"  Pairs with similarity >= 0.50 ({len(above_thresh)} pairs):")
            for s, r_art, c_art in sorted(above_thresh, key=lambda x: x[0], reverse=True):
                allowed, rsn = guard.is_merge_allowed(r_art, c_art)
                print(f"    - Sim: {s:.4f} | Allowed: {allowed} ({rsn}) | \"{r_art.title[:35]}\" vs \"{c_art.title[:35]}\"")
        else:
            print("  No pairs with similarity >= 0.50 in this domain.")

if __name__ == "__main__":
    main()
