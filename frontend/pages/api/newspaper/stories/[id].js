import { getCurrentEdition } from '../../../../lib/editions.js';

export default async function handler(req, res) {
  const { id } = req.query;
  if (!id) {
    return res.status(400).json({ error: 'Story ID is required' });
  }

  try {
    const edition = await getCurrentEdition();
    if (!edition || !edition.stories) {
      return res.status(404).json({ error: `Story cluster '${id}' not found (no active edition).` });
    }

    const story = edition.stories.find(
      s => s.story_id === id || s.url === id || encodeURIComponent(s.story_id) === encodeURIComponent(id)
    );

    if (!story) {
      return res.status(404).json({ error: `Story cluster '${id}' not found in current edition.` });
    }

    const members = (story.sources && story.sources.length > 0 ? story.sources : ['Primary Source']).map((src, idx) => ({
      article_id: `${story.story_id}_${idx}`,
      title: story.title,
      url: story.url,
      canonical_url: story.url,
      source: src,
      author: null,
      published_at: story.published_at,
      domain: story.domain,
      topic: story.topic || 'General',
      relevance_score: story.relevance_score || 1.0,
      is_representative: idx === 0,
      is_meaningful_update: false,
      update_reason: null,
      added_at: story.first_seen_at,
      excerpt: story.summary,
      image_url: story.image_url || (story.raw_metadata && story.raw_metadata.image_url) || null,
    }));

    return res.status(200).json({
      cluster_id: story.story_id,
      headline: story.title,
      summary: story.summary,
      domain: story.domain,
      topic: story.topic || 'General',
      published_at: story.published_at,
      first_seen_at: story.first_seen_at,
      last_seen_at: story.first_seen_at,
      representative_source: story.sources && story.sources.length > 0 ? story.sources[0] : 'Unknown',
      representative_url: story.url,
      source_count: story.sources ? story.sources.length : 1,
      sources: story.sources || [],
      image_url: story.image_url || (story.raw_metadata && story.raw_metadata.image_url) || null,
      lifecycle_status: 'ACTIVE',
      members,
    });
  } catch (err) {
    console.error('Error fetching story detail:', err);
    return res.status(500).json({
      error: 'Failed to retrieve story details',
      message: err.message,
    });
  }
}
