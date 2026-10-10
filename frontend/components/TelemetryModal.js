import React, { useEffect, useState } from 'react';
import { X, Activity, Database, CheckCircle2, Clock, AlertTriangle, Layers } from 'lucide-react';
import { fetchHealth, fetchRecentRuns } from '../lib/api';

export default function TelemetryModal({ onClose }) {
  const [health, setHealth] = useState(null);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    setLoading(true);

    Promise.all([fetchHealth().catch(() => null), fetchRecentRuns(10).catch(() => ({ items: [] }))])
      .then(([healthData, runsData]) => {
        if (mounted) {
          setHealth(healthData);
          setRuns(runsData.items || []);
          setLoading(false);
        }
      });

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      mounted = false;
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [onClose]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 880 }}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Activity size={18} color="var(--border-dark)" />
            <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: '1.25rem', fontWeight: 700 }}>
              Pipeline Telemetry &amp; Diagnostics
            </h3>
          </div>
          <button className="modal-close-btn" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="modal-body">
          {/* Storage & Engine Metrics */}
          {health && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16, marginBottom: 28 }}>
              <div style={{ background: 'var(--bg-subtle)', padding: 16, borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>Database Status</div>
                <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#15803d', marginTop: 4 }}>
                  {health.database_connected ? 'Connected (SQLite)' : 'Disconnected'}
                </div>
              </div>
              <div style={{ background: 'var(--bg-subtle)', padding: 16, borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>Total Articles</div>
                <div style={{ fontSize: '1.25rem', fontWeight: 700, marginTop: 4 }}>
                  {health.database_stats.total_articles || 0}
                </div>
              </div>
              <div style={{ background: 'var(--bg-subtle)', padding: 16, borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>Active Story Clusters</div>
                <div style={{ fontSize: '1.25rem', fontWeight: 700, marginTop: 4 }}>
                  {health.database_stats.total_story_clusters || 0}
                </div>
              </div>
              <div style={{ background: 'var(--bg-subtle)', padding: 16, borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>Database Size</div>
                <div style={{ fontSize: '1.25rem', fontWeight: 700, marginTop: 4 }}>
                  {((health.database_stats.db_size_bytes || 0) / 1024).toFixed(1)} KB
                </div>
              </div>
            </div>
          )}

          {/* Recent Runs Table */}
          <h4 style={{ fontFamily: 'var(--font-serif)', fontSize: '1.1rem', marginBottom: 12 }}>
            Execution Run History
          </h4>

          {loading ? (
            <div style={{ textAlign: 'center', padding: 20, color: 'var(--text-muted)' }}>Loading telemetry...</div>
          ) : runs.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 20, color: 'var(--text-muted)' }}>No recorded pipeline runs yet.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                <thead>
                  <tr style={{ background: 'var(--bg-subtle)', textAlign: 'left', borderBottom: '1px solid var(--border-color)' }}>
                    <th style={{ padding: '8px 12px' }}>Run ID</th>
                    <th style={{ padding: '8px 12px' }}>Trigger</th>
                    <th style={{ padding: '8px 12px' }}>Status</th>
                    <th style={{ padding: '8px 12px' }}>Candidates</th>
                    <th style={{ padding: '8px 12px' }}>Clusters</th>
                    <th style={{ padding: '8px 12px' }}>Duration</th>
                    <th style={{ padding: '8px 12px' }}>Started At</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.run_id} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontSize: '0.8rem' }}>{r.run_id}</td>
                      <td style={{ padding: '8px 12px', fontWeight: 600 }}>{r.trigger_type}</td>
                      <td style={{ padding: '8px 12px' }}>
                        <span
                          style={{
                            padding: '2px 8px',
                            borderRadius: 4,
                            fontWeight: 700,
                            fontSize: '0.75rem',
                            background: r.status === 'COMPLETED' ? '#dcfce7' : r.status === 'RUNNING' ? '#fef3c7' : '#fee2e2',
                            color: r.status === 'COMPLETED' ? '#15803d' : r.status === 'RUNNING' ? '#b45309' : '#b91c1c',
                          }}
                        >
                          {r.status}
                        </span>
                      </td>
                      <td style={{ padding: '8px 12px' }}>{r.candidates_evaluated ?? '-'}</td>
                      <td style={{ padding: '8px 12px' }}>{r.clusters_formed ?? '-'}</td>
                      <td style={{ padding: '8px 12px' }}>
                        {r.duration_seconds != null ? `${r.duration_seconds.toFixed(1)}s` : '-'}
                      </td>
                      <td style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>
                        {r.started_at ? new Date(r.started_at).toLocaleTimeString() : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
