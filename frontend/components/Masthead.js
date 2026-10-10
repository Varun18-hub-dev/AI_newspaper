import React from 'react';
import { RefreshCw, Activity, Calendar, Newspaper, AlertCircle, Compass } from 'lucide-react';

export default function Masthead({ latestRun, onRefresh, isRefreshing, refreshError, onOpenTelemetry }) {
  const currentDate = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });

  const getStatusBadge = () => {
    if (!latestRun) {
      return (
        <div className="masthead-status-pill" onClick={onOpenTelemetry} title="System Status: Ready">
          <span className="status-dot-indicator"></span>
          <span>Daily Edition • Ready</span>
        </div>
      );
    }

    const isRunning = isRefreshing || latestRun.status === 'RUNNING';
    const isSuccess = latestRun.status === 'COMPLETED' || latestRun.status === 'SUCCESS';
    const isFailed = latestRun.status === 'FAILED';

    return (
      <div
        className="masthead-status-pill"
        onClick={onOpenTelemetry}
        title="Click to view run history & system diagnostics"
      >
        <span className={`status-dot-indicator ${isRunning ? 'running' : isFailed ? 'failed' : ''}`}></span>
        <span>
          {isRunning
            ? 'Ingestion in Progress…'
            : isSuccess
            ? `Edition Current (${latestRun.clusters_formed || 0} Stories)`
            : 'Edition Degraded'}
        </span>
        <Activity size={13} style={{ marginLeft: 3, opacity: 0.7 }} />
      </div>
    );
  };

  return (
    <header className="masthead">
      <div className="container">
        {/* Top Folio Bar */}
        <div className="masthead-top-bar">
          <div className="masthead-weather-date">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <Calendar size={13} /> {currentDate}
            </span>
            <span>•</span>
            <span className="edition-vol-tag">Vol. I, No. 28</span>
            <span>•</span>
            <span>Global Wire Service</span>
          </div>
          <div>{getStatusBadge()}</div>
        </div>

        {/* Center Broadsheet Title */}
        <div className="masthead-branding">
          <div className="masthead-kicker">Independent Multi-Source Journalism</div>
          <h1 className="masthead-name">The Curated Dispatch</h1>
          <p className="masthead-motto">
            Synthesized by Local Intelligence • Multi-Source Attributed • Clustered from 23 Verified Publishers
          </p>
        </div>

        {/* Meta Bar & Actions */}
        <div className="masthead-meta-bar">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: '0.8rem', color: 'var(--ink-secondary)' }}>
            <span>
              <strong>Desk:</strong> Automated Global Edition
            </span>
            <span>•</span>
            <span>
              <strong>Wire Feeds:</strong> arXiv, Hacker News, GitHub, NVD, Ars Technica, Nature &amp; TechCrunch
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <button
              className="editorial-btn secondary"
              onClick={onOpenTelemetry}
              title="View Run History & Operational Telemetry"
            >
              <Activity size={13} />
              Telemetry
            </button>
            <button
              className="editorial-btn primary"
              onClick={onRefresh}
              disabled={isRefreshing}
              title="Trigger an on-demand RSS news discovery run"
            >
              <RefreshCw
                size={13}
                style={{
                  animation: isRefreshing ? 'spin 1s linear infinite' : 'none',
                }}
              />
              {isRefreshing ? 'Ingesting Feeds…' : 'Fetch Latest News'}
            </button>
          </div>
        </div>

        {refreshError && (
          <div
            style={{
              marginTop: 12,
              marginBottom: 8,
              padding: '8px 14px',
              borderRadius: 'var(--radius-xs)',
              background: '#fee2e2',
              border: '1px solid #f87171',
              color: '#991b1b',
              fontSize: '0.82rem',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <AlertCircle size={15} />
            <span>{refreshError}</span>
          </div>
        )}
      </div>
    </header>
  );
}
