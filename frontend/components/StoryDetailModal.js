import React, { useEffect, useState } from 'react';
import { X, ExternalLink, Globe, Star, Clock, ShieldCheck } from 'lucide-react';
import { fetchStoryDetail } from '../lib/api';
import ArticleImage from './ArticleImage';

export default function StoryDetailModal({ story, onClose }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!story || !story.cluster_id) return;

    let mounted = true;
    setLoading(true);
    setError(null);

    fetchStoryDetail(story.cluster_id)
      .then((data) => {
        if (mounted) {
          setDetail(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (mounted) {
          setError(err.message || 'Failed to load story details.');
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
  }, [story, onClose]);

  if (!story) return null;

  const imageUrl = story.image_url || (detail && detail.image_url);

  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.78rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--accent-burgundy)' }}>
              {story.domain}
            </span>
            {story.topic && story.topic !== 'General' && (
              <span style={{ fontSize: '0.78rem', color: 'var(--ink-muted)', fontWeight: 600 }}>
                • {story.topic}
              </span>
            )}
            <span style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', fontFamily: 'var(--font-mono)' }}>
              (Ref: {story.cluster_id})
            </span>
          </div>
          <button className="editorial-btn secondary" onClick={onClose} title="Close Dossier (Esc)">
            <X size={16} /> Close
          </button>
        </div>

        <div className="modal-body">
          {/* Optional Hero Article Image */}
          {imageUrl && (
            <div style={{ marginBottom: 20 }}>
              <ArticleImage
                src={imageUrl}
                alt={story.headline}
                aspectRatio="16/9"
                caption={`Featured reporting via ${story.representative_source}`}
              />
            </div>
          )}

          <h2 className="modal-headline">{story.headline}</h2>

          <div className="modal-summary-box">
            <div style={{ fontWeight: 700, marginBottom: 6, fontSize: '0.76rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--accent-burgundy)' }}>
              Synthesized Overview &amp; Key Evidence
            </div>
            {story.summary || 'Summary unavailable for this cluster. Inspect member articles below.'}
          </div>

          <h3 className="members-section-title">
            Primary Reporting &amp; Attributed Dispatches ({story.source_count || (detail && detail.members ? detail.members.length : 1)} Sources)
          </h3>

          {loading && (
            <div style={{ textAlign: 'center', padding: '30px 0', color: 'var(--ink-muted)', fontStyle: 'italic', fontFamily: 'var(--font-reading)' }}>
              Retrieving syndication breakdown from database…
            </div>
          )}

          {error && (
            <div style={{ padding: '14px', background: '#fee2e2', color: '#991b1b', border: '1px solid #f87171', borderRadius: 'var(--radius-xs)', marginBottom: 16 }}>
              {error}
            </div>
          )}

          {detail && detail.members && detail.members.map((member) => (
            <div
              key={member.article_id}
              className={`member-article-card ${member.is_representative ? 'primary' : ''}`}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Globe size={13} color="var(--ink-muted)" />
                  <strong style={{ fontSize: '0.86rem' }}>{member.source}</strong>
                  {member.is_representative && (
                    <span
                      style={{
                        background: '#e0f2fe',
                        color: '#0369a1',
                        fontSize: '0.68rem',
                        fontWeight: 700,
                        padding: '1px 6px',
                        borderRadius: 2,
                        textTransform: 'uppercase',
                        letterSpacing: '0.04em',
                      }}
                    >
                      Lead Dispatch
                    </span>
                  )}
                  {member.is_meaningful_update && (
                    <span style={{ background: '#fef3c7', color: '#92400e', fontSize: '0.68rem', fontWeight: 700, padding: '1px 6px', borderRadius: 2 }}>
                      ⚡ Update
                    </span>
                  )}
                </div>
                {member.published_at && (
                  <span style={{ fontSize: '0.72rem', color: 'var(--ink-muted)' }}>
                    {new Date(member.published_at).toLocaleDateString('en-US', {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </span>
                )}
              </div>

              <h4 style={{ fontFamily: 'var(--font-serif)', fontSize: '1.1rem', fontWeight: 700, lineHeight: 1.35, marginBottom: 8 }}>
                {member.title}
              </h4>

              {member.excerpt && (
                <p style={{ fontFamily: 'var(--font-reading)', fontSize: '0.92rem', color: 'var(--ink-secondary)', lineHeight: 1.55, marginBottom: 12 }}>
                  {member.excerpt}
                </p>
              )}

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px dashed var(--rule-fine)', paddingTop: 8 }}>
                <span style={{ fontSize: '0.72rem', color: 'var(--ink-muted)' }}>
                  {member.author ? `By ${member.author}` : `Via ${member.source}`}
                </span>
                <a
                  href={member.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="editorial-btn secondary"
                  style={{ textDecoration: 'none' }}
                >
                  Original Source <ExternalLink size={12} />
                </a>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
