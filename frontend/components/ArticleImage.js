import React, { useState } from 'react';

/**
 * Reusable ArticleImage component for editorial newspaper cards.
 *
 * Requirements:
 * - Images are strictly optional.
 * - Renders NOTHING (null) if src is missing, empty, or fails to load (onError).
 * - Never shows broken image icons, empty skeleton placeholders, or repeated generic stock photos.
 * - Uses standard responsive aspect ratios and object-fit: cover.
 */
export default function ArticleImage({
  src,
  alt = '',
  className = '',
  aspectRatio = '16/9',
  style = {},
  caption = null,
}) {
  const [hasError, setHasError] = useState(false);
  const [isLoaded, setIsLoaded] = useState(false);

  // Genuinely optional: if no usable URL or error occurred, render zero DOM elements
  if (!src || typeof src !== 'string' || !src.trim() || hasError) {
    return null;
  }

  const cleanSrc = src.trim();
  // Filter out invalid/empty/data: placeholder strings
  if (!cleanSrc.startsWith('http://') && !cleanSrc.startsWith('https://')) {
    return null;
  }

  return (
    <figure className={`article-image-container ${className}`} style={{ aspectRatio, ...style }}>
      <img
        src={cleanSrc}
        alt={alt || 'Article editorial illustration'}
        loading="lazy"
        onError={() => setHasError(true)}
        onLoad={() => setIsLoaded(true)}
        className={`article-image ${isLoaded ? 'loaded' : ''}`}
      />
      {caption && isLoaded && (
        <figcaption className="article-image-caption">{caption}</figcaption>
      )}
    </figure>
  );
}
