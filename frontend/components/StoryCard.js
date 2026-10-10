import React from 'react';
import { Clock, Globe, ArrowUpRight, Sparkles, FileText } from 'lucide-react';
import ArticleImage from './ArticleImage';

/**
 * Editorial StoryCard component.
 *
 * Requirements:
 * - Premium broadsheet newspaper styling with serif headlines and refined typography.
 * - Displays headline, summary, source/publisher, published date, domain category, and multi-source attribution.
 * - Optional image support via ArticleImage: renders image only when valid, cleanly folds to text-first layout when absent or broken.
 * - Text-only cards remain visually balanced and intentional.
 */
export default function StoryCard({
  story,
  isLead = false,
  isHighlight = false,
  highlightIndex = null,
  onClick,
}) {
  if (!story) return null;

  const domain = story.domain || 'General';
  const topic = story.topic && story.topic !== 'General' ? story.topic : null;

  const formattedDate = story.published_at
    ? new Date(story.published_at).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : 'Latest Wire';

  const multiSourceText =
    story.source_count > 1
      ? `${story.source_count} Sources (${story.sources.slice(0, 2).join(', ')}${story.sources.length > 2 ? '…' : ''})`
      : story.representative_source || 'Dispatched Source';

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onClick && onClick(story);
    }
  };

  // 1. Featured Lead Story Layout
  if (isLead) {
    const hasImage = Boolean(story.image_url);

    return (
      <article
        className="lead-story-editorial"
        onClick={() => onClick && onClick(story)}
        onKeyDown={handleKeyDown}
        tabIndex={0}
        role="button"
        aria-label={`Lead story: ${story.headline}`}
      >
        <div className={`lead-story-grid ${!hasImage ? 'text-only' : ''}`}>
          <div>
            <div className="lead-kicker">
              <span>{domain}</span>
              {topic && <span>• {topic}</span>}
              {story.has_updates && (
                <span style={{ color: 'var(--accent-amber)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <Sparkles size={12} /> Developing
                </span>
              )}
            </div>

            <h2 className="lead-headline">{story.headline}</h2>
            <p className="lead-summary">
              {story.summary || 'Summary overview unavailable. Select to inspect primary dispatches and source coverage.'}
            </p>

            <div className="lead-byline">
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span className="multi-source-tag">
                  <Globe size={12} /> {multiSourceText}
                </span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <Clock size={12} /> {formattedDate}
                </span>
              </div>
              <span style={{ fontWeight: 600, color: 'var(--accent-burgundy)', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                Full Dossier <ArrowUpRight size={14} />
              </span>
            </div>
          </div>

          {/* Optional Lead Image: renders nothing if image_url is missing or fails */}
          {hasImage && (
            <div>
              <ArticleImage
                src={story.image_url}
                alt={story.headline}
                aspectRatio="16/10"
                caption={`Illustration via ${story.representative_source}`}
              />
            </div>
          )}
        </div>
      </article>
    );
  }

  // 2. Today's Highlights Column Card
  if (isHighlight) {
    const romanNumerals = ['I', 'II', 'III', 'IV', 'V'];
    const indexLabel = highlightIndex !== null ? romanNumerals[highlightIndex] || `${highlightIndex + 1}` : '•';

    return (
      <article
        className="highlight-column-card"
        onClick={() => onClick && onClick(story)}
        onKeyDown={handleKeyDown}
        tabIndex={0}
        role="button"
        aria-label={`Highlight ${indexLabel}: ${story.headline}`}
      >
        <div>
          <div className="highlight-number">{indexLabel}</div>
          <div className="card-kicker-bar">
            <span>{domain} {topic ? `• ${topic}` : ''}</span>
          </div>

          {/* Optional Image */}
          {story.image_url && (
            <ArticleImage
              src={story.image_url}
              alt={story.headline}
              aspectRatio="16/9"
            />
          )}

          <h3 className="card-headline-text" style={{ fontSize: '1.15rem' }}>
            {story.headline}
          </h3>
          <p className="card-summary-text" style={{ WebkitLineClamp: 3 }}>
            {story.summary || 'Click to view full coverage and quotes.'}
          </p>
        </div>

        <div className="card-footer-meta">
          <span className="multi-source-tag">
            <Globe size={11} /> {multiSourceText}
          </span>
          <span>{formattedDate}</span>
        </div>
      </article>
    );
  }

  // 3. Standard Broadsheet Story Card
  return (
    <article
      className="editorial-card"
      onClick={() => onClick && onClick(story)}
      onKeyDown={handleKeyDown}
      tabIndex={0}
      role="button"
      aria-label={`Article: ${story.headline}`}
    >
      <div>
        <div className="card-kicker-bar">
          <span>{domain} {topic ? `• ${topic}` : ''}</span>
          {story.has_updates && (
            <span style={{ color: 'var(--accent-amber)', fontSize: '0.7rem' }}>
              • Update
            </span>
          )}
        </div>

        {/* Optional Article Image */}
        {story.image_url && (
          <ArticleImage
            src={story.image_url}
            alt={story.headline}
            aspectRatio="16/9"
          />
        )}

        <h3 className="card-headline-text">{story.headline}</h3>
        <p className="card-summary-text">
          {story.summary || 'Click to inspect detailed source reports and excerpts.'}
        </p>
      </div>

      <div className="card-footer-meta">
        <span className="multi-source-tag">
          <Globe size={11} /> {multiSourceText}
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <Clock size={11} /> {formattedDate}
        </span>
      </div>
    </article>
  );
}
