import { getCurrentEdition } from '../../../lib/editions.js';

export default async function handler(req, res) {
  // Allow caching: short cache for current pointer to discover new editions quickly
  res.setHeader('Cache-Control', 'public, s-maxage=60, stale-while-revalidate=300');

  try {
    const { domain, topic, page = '1', page_size = '12' } = req.query;
    const pageNum = Math.max(1, parseInt(page, 10) || 1);
    const pageSize = Math.min(50, Math.max(1, parseInt(page_size, 10) || 12));

    const edition = await getCurrentEdition();

    if (!edition || !edition.stories) {
      return res.status(200).json({
        items: [],
        total: 0,
        page: pageNum,
        page_size: pageSize,
        total_pages: 1,
        domain_filter: domain || null,
        topic_filter: topic || null,
        edition_id: null,
        published_at: null,
        is_stale: false,
      });
    }

function normalizeDomainKey(d) {
  if (!d) return '';
  const s = d.trim().toLowerCase();
  if (s === 'ai' || s.includes('artificial intelligence') || s.includes('intelligence')) return 'ai';
  if (s === 'technology' || (s.includes('tech') && !s.includes('biotech'))) return 'technology';
  if (s === 'science' || s.includes('sci')) return 'science';
  if (s === 'cybersecurity' || s.includes('cyber') || s.includes('security')) return 'cybersecurity';
  if (s === 'business' || s.includes('business') || s.includes('startup')) return 'business';
  return s;
}

    let filteredStories = edition.stories;

    if (domain && domain !== 'all') {
      const targetDomain = normalizeDomainKey(domain);
      filteredStories = filteredStories.filter(
        s => normalizeDomainKey(s.domain) === targetDomain
      );
    }

    if (topic && topic !== 'all') {
      const normTopic = topic.trim().toLowerCase();
      filteredStories = filteredStories.filter(
        s => (s.topic || '').toLowerCase() === normTopic
      );
    }

    const total = filteredStories.length;
    const totalPages = total > 0 ? Math.ceil(total / pageSize) : 1;
    const startIndex = (pageNum - 1) * pageSize;
    const pagedSlice = filteredStories.slice(startIndex, startIndex + pageSize);

    // Compute staleness (> 24 hours)
    let isStale = false;
    if (edition.published_at) {
      try {
        const pubTime = new Date(edition.published_at).getTime();
        if (!isNaN(pubTime)) {
          isStale = Date.now() - pubTime > 24 * 60 * 60 * 1000;
        }
      } catch (err) {
        // Ignore date parsing error
      }
    }

    const items = pagedSlice.map(s => ({
      cluster_id: s.story_id,
      headline: s.title,
      summary: s.summary,
      domain: s.domain,
      topic: s.topic || 'General',
      published_at: s.published_at,
      first_seen_at: s.first_seen_at,
      representative_source: s.sources && s.sources.length > 0 ? s.sources[0] : 'Unknown',
      representative_url: s.url,
      source_count: s.sources ? s.sources.length : 1,
      sources: s.sources || [],
      relevance_score: s.relevance_score || 1.0,
      member_count: s.sources ? s.sources.length : 1,
      image_url: s.image_url || (s.raw_metadata && s.raw_metadata.image_url) || null,
    }));

    return res.status(200).json({
      items,
      total,
      page: pageNum,
      page_size: pageSize,
      total_pages: totalPages,
      domain_filter: domain || null,
      topic_filter: topic || null,
      edition_id: edition.edition_id,
      published_at: edition.published_at,
      is_stale: isStale,
    });
  } catch (err) {
    console.error('Error fetching latest edition stories:', err);
    return res.status(500).json({
      error: 'Failed to retrieve newspaper edition',
      message: err.message,
    });
  }
}
