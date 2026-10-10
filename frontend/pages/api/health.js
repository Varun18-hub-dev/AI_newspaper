import { getCurrentPointer } from '../../lib/editions.js';

export default async function handler(req, res) {
  try {
    const pointer = await getCurrentPointer();
    return res.status(200).json({
      status: 'ok',
      timestamp: new Date().toISOString(),
      version: '1.0.0',
      database_connected: true,
      serverless_mode: true,
      current_edition: pointer ? pointer.edition_id : null,
      total_stories: pointer ? pointer.total_stories : 0,
      database_stats: {
        current_edition: pointer ? pointer.edition_id : null,
        total_stories: pointer ? pointer.total_stories : 0,
      },
    });
  } catch (err) {
    return res.status(200).json({
      status: 'degraded',
      timestamp: new Date().toISOString(),
      version: '1.0.0',
      database_connected: false,
      serverless_mode: true,
      error: err.message,
    });
  }
}
