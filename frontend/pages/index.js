import React, { useEffect, useState, useCallback, useRef } from 'react';
import Masthead from '../components/Masthead';
import DomainNav from '../components/DomainNav';
import StoryCard from '../components/StoryCard';
import StoryDetailModal from '../components/StoryDetailModal';
import TelemetryModal from '../components/TelemetryModal';
import {
  fetchDomains,
  fetchLatestStories,
  fetchLatestRun,
  triggerManualRefresh,
} from '../lib/api';
import { AlertCircle, ChevronLeft, ChevronRight, RefreshCw, Newspaper, Clock, Globe } from 'lucide-react';

export default function Home() {
  const [domains, setDomains] = useState([]);
  const [selectedDomain, setSelectedDomain] = useState('all');
  const [selectedTopic, setSelectedTopic] = useState('all');
  const [page, setPage] = useState(1);
  const [storiesData, setStoriesData] = useState({ items: [], total: 0, total_pages: 1 });
  const [latestRun, setLatestRun] = useState(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState(null);

  const [selectedStory, setSelectedStory] = useState(null);
  const [isTelemetryOpen, setIsTelemetryOpen] = useState(false);

  const pollIntervalRef = useRef(null);

  // Load domains & telemetry initially
  const loadInitialMetadata = useCallback(async () => {
    try {
      const [domRes, runRes] = await Promise.all([
        fetchDomains().catch(() => ({ domains: [] })),
        fetchLatestRun().catch(() => null),
      ]);
      setDomains(domRes.domains || []);
      setLatestRun(runRes);
    } catch (err) {
      console.error('Failed to load initial metadata:', err);
    }
  }, []);

  // Fetch stories whenever domain, topic, or page changes
  const loadStories = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchLatestStories({
        domain: selectedDomain === 'all' ? null : selectedDomain,
        topic: selectedTopic === 'all' ? null : selectedTopic,
        page,
        pageSize: 16,
      });
      setStoriesData(data);
    } catch (err) {
      setError(
        'Unable to load news edition from the server. Ensure the backend API is running on http://127.0.0.1:8000.'
      );
    } finally {
      setLoading(false);
    }
  }, [selectedDomain, selectedTopic, page]);

  useEffect(() => {
    loadInitialMetadata();
  }, [loadInitialMetadata]);

  useEffect(() => {
    loadStories();
  }, [loadStories]);

  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  // Handle Manual Refresh
  const handleRefresh = async () => {
    if (isRefreshing) return;
    setIsRefreshing(true);
    setRefreshError(null);

    try {
      await triggerManualRefresh(selectedDomain === 'all' ? null : selectedDomain);

      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = setInterval(async () => {
        try {
          const run = await fetchLatestRun();
          setLatestRun(run);
          if (run && (run.status === 'COMPLETED' || run.status === 'SUCCESS' || run.status === 'FAILED')) {
            clearInterval(pollIntervalRef.current);
            setIsRefreshing(false);
            loadInitialMetadata();
            loadStories();
          }
        } catch (pollErr) {
          console.warn('Polling error:', pollErr);
        }
      }, 3000);
    } catch (err) {
      setIsRefreshing(false);
      setRefreshError(err.message || 'Manual refresh failed.');
    }
  };

  const handleDomainSelect = (domainId) => {
    setSelectedDomain(domainId);
    setSelectedTopic('all');
    setPage(1);
  };

  const handleTopicSelect = (topicName) => {
    setSelectedTopic(topicName);
    setPage(1);
  };

  const stories = storiesData.items || [];
  const isFrontPage = selectedDomain === 'all' && page === 1;

  // Editorial Breakdown:
  // Lead Story (Story 0)
  const leadStory = stories.length > 0 ? stories[0] : null;
  // Today's Highlights (Stories 1, 2, 3 if on Front Page)
  const highlightStories = isFrontPage && stories.length >= 4 ? stories.slice(1, 4) : [];
  // Main Grid Stories
  const mainGridStories = isFrontPage && stories.length >= 4
    ? stories.slice(4, Math.max(4, stories.length - 4))
    : (page === 1 ? stories.slice(1) : stories);
  // News Wire Briefs (compact sidebar)
  const wireStories = stories.length >= 6
    ? stories.slice(Math.max(4, stories.length - 4))
    : stories.slice(1, 4);

  return (
    <div className="newspaper-wrapper">
      <Masthead
        latestRun={latestRun}
        onRefresh={handleRefresh}
        isRefreshing={isRefreshing}
        refreshError={refreshError}
        onOpenTelemetry={() => setIsTelemetryOpen(true)}
      />

      <DomainNav
        domains={domains}
        selectedDomain={selectedDomain}
        onSelectDomain={handleDomainSelect}
        selectedTopic={selectedTopic}
        onSelectTopic={handleTopicSelect}
      />

      <main className="container broadsheet-main">
        {/* Stale Edition Banner */}
        {storiesData.is_stale && (
          <div className="stale-edition-notice">
            <AlertCircle size={16} />
            <span>
              <strong>Archive Notice:</strong> Currently serving edition{' '}
              <code>{storiesData.edition_id || 'yesterday'}</code>. The automated morning publication cycle is scheduled.
            </span>
          </div>
        )}

        {/* Section Header Bar */}
        <div className="section-headline-bar">
          <h2 className="section-headline-title">
            {selectedDomain === 'all'
              ? 'Front Page Edition'
              : domains.find((d) => d.domain_id === selectedDomain)?.display_name || selectedDomain}
          </h2>
          <div className="section-headline-meta">
            {selectedTopic && selectedTopic !== 'all' ? `Desk: ${selectedTopic} • ` : ''}
            {storiesData.total} {storiesData.total === 1 ? 'Dispatch' : 'Dispatches'} Cataloged
          </div>
        </div>

        {/* Error State */}
        {error && (
          <div className="state-box">
            <AlertCircle size={36} color="var(--accent-burgundy)" style={{ margin: '0 auto 12px' }} />
            <h3 className="state-title">Newsroom Feed Offline</h3>
            <p className="state-desc">{error}</p>
            <button className="editorial-btn primary" onClick={loadStories}>
              <RefreshCw size={13} /> Reconnect Wire
            </button>
          </div>
        )}

        {/* Loading State */}
        {loading && (
          <div className="state-box">
            <RefreshCw
              size={32}
              color="var(--ink-muted)"
              style={{ margin: '0 auto 16px', animation: 'spin 1.2s linear infinite' }}
            />
            <h3 className="state-title">Assembling Broadsheet Edition</h3>
            <p className="state-desc">Synthesizing dispatches, verifying multi-source attributions, and formatting typography…</p>
            <style jsx>{`
              @keyframes spin {
                from { transform: rotate(0deg); }
                to { transform: rotate(360deg); }
              }
            `}</style>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && stories.length === 0 && (
          <div className="state-box">
            <Newspaper size={36} color="var(--ink-muted)" style={{ margin: '0 auto 12px' }} />
            <h3 className="state-title">No Stories Filed For This Desk Today</h3>
            <p className="state-desc">
              No articles currently meet the relevance and verification threshold for this department.
              Check other sections or trigger an on-demand wire fetch.
            </p>
            <button className="editorial-btn secondary" onClick={() => handleDomainSelect('all')}>
              Return to Front Page
            </button>
          </div>
        )}

        {/* Newspaper Editorial Presentation */}
        {!loading && !error && stories.length > 0 && (
          <>
            {/* 1. Featured Lead Story */}
            {leadStory && page === 1 && (
              <StoryCard
                story={leadStory}
                isLead={true}
                onClick={(s) => setSelectedStory(s)}
              />
            )}

            {/* 2. Today's Highlights (3-Column Layout on Front Page) */}
            {highlightStories.length > 0 && (
              <div className="highlights-container">
                <div className="section-headline-bar" style={{ marginBottom: 12 }}>
                  <h3 className="section-headline-title" style={{ fontSize: '1.15rem' }}>
                    Today&apos;s Highlights
                  </h3>
                  <span className="section-headline-meta">Curated Multi-Source Key Developments</span>
                </div>
                <div className="highlights-columns">
                  {highlightStories.map((story, idx) => (
                    <StoryCard
                      key={story.cluster_id}
                      story={story}
                      isHighlight={true}
                      highlightIndex={idx}
                      onClick={(s) => setSelectedStory(s)}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* 3. Broadsheet Two-Column: Department Stories + News Wire Sidebar */}
            <div className="broadsheet-columns">
              {/* Primary Column */}
              <div>
                <div className="section-headline-bar" style={{ marginBottom: 18 }}>
                  <h3 className="section-headline-title" style={{ fontSize: '1.2rem' }}>
                    {isFrontPage ? 'Department Reporting' : 'Section Dispatches'}
                  </h3>
                  <span className="section-headline-meta">In-Depth Analysis</span>
                </div>

                <div className="broadsheet-primary-grid">
                  {(mainGridStories.length > 0 ? mainGridStories : (leadStory && page !== 1 ? stories : [])).map((story) => (
                    <StoryCard
                      key={story.cluster_id}
                      story={story}
                      onClick={(s) => setSelectedStory(s)}
                    />
                  ))}
                </div>
              </div>

              {/* Wire Briefs Sidebar */}
              <aside className="news-wire-sidebar">
                <div className="wire-header">
                  <h4 className="wire-title">Latest Wire Briefs</h4>
                  <Clock size={14} style={{ opacity: 0.6 }} />
                </div>

                <div>
                  {wireStories.map((story) => (
                    <div
                      key={story.cluster_id}
                      className="wire-item"
                      onClick={() => setSelectedStory(story)}
                      role="button"
                      tabIndex={0}
                    >
                      <div className="wire-timestamp">
                        <span style={{ fontWeight: 700, color: 'var(--accent-burgundy)' }}>{story.domain}</span>
                        <span>•</span>
                        <span>{story.representative_source}</span>
                      </div>
                      <h5 className="wire-headline">{story.headline}</h5>
                    </div>
                  ))}
                </div>
              </aside>
            </div>

            {/* Pagination Bar */}
            {storiesData.total_pages > 1 && (
              <div className="pagination-bar">
                <button
                  className="editorial-btn secondary"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                >
                  <ChevronLeft size={14} /> Previous Page
                </button>
                <span className="page-counter-text">
                  Page {storiesData.page} of {storiesData.total_pages}
                </span>
                <button
                  className="editorial-btn secondary"
                  onClick={() => setPage((p) => Math.min(storiesData.total_pages, p + 1))}
                  disabled={page >= storiesData.total_pages}
                >
                  Next Page <ChevronRight size={14} />
                </button>
              </div>
            )}
          </>
        )}
      </main>

      {/* Story Detail Dossier Modal */}
      {selectedStory && (
        <StoryDetailModal
          story={selectedStory}
          onClose={() => setSelectedStory(null)}
        />
      )}

      {/* Diagnostics / Telemetry Modal */}
      {isTelemetryOpen && (
        <TelemetryModal onClose={() => setIsTelemetryOpen(false)} />
      )}
    </div>
  );
}
