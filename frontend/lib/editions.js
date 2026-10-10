import fs from 'fs';
import path from 'path';

/**
 * Server-side helper to read published newspaper editions from disk or remote S3/CDN.
 * Used by Next.js API routes to eliminate the need for an always-on backend server.
 */

function getEditionsDirPath() {
  if (process.env.EDITIONS_DIR) {
    return path.resolve(process.env.EDITIONS_DIR);
  }
  const candidates = [
    path.join(process.cwd(), 'data', 'editions'),
    path.join(process.cwd(), '..', 'data', 'editions'),
    path.resolve(process.cwd(), '../data/editions'),
  ];

  for (const cand of candidates) {
    if (fs.existsSync(cand)) return cand;
  }

  return candidates[0];
}

export async function getCurrentPointer() {
  const remoteBase = process.env.EDITIONS_BASE_URL;
  if (remoteBase) {
    const baseUrl = remoteBase.replace(/\/$/, '');
    const remoteUrls = [
      `${baseUrl}/current_edition.json`,
      `${baseUrl}/editions/current_edition.json`,
    ];
    for (const url of remoteUrls) {
      try {
        const res = await fetch(url, { cache: 'no-store' });
        if (res.ok) {
          return await res.json();
        }
      } catch (err) {
        console.warn(`Failed to fetch remote current_edition pointer from ${url}:`, err.message);
      }
    }
    return null;
  }

  // Local file read
  try {
    const dir = getEditionsDirPath();
    if (!dir || !fs.existsSync(dir)) {
      return null;
    }

    const filePath = path.join(dir, 'current_edition.json');
    if (fs.existsSync(filePath)) {
      const raw = fs.readFileSync(filePath, 'utf8');
      return JSON.parse(raw);
    }

    // Fallback: If pointer file is missing, automatically discover newest edition_*.json
    const files = fs.readdirSync(dir).filter(f => f.startsWith('edition_') && f.endsWith('.json'));
    if (files.length > 0) {
      files.sort().reverse();
      const latestFile = path.join(dir, files[0]);
      const rawManifest = fs.readFileSync(latestFile, 'utf8');
      const manifest = JSON.parse(rawManifest);
      return {
        edition_id: manifest.edition_id,
        published_at: manifest.published_at,
        checksum: manifest.checksum,
        total_stories: manifest.total_stories,
        run_id: manifest.run_id,
      };
    }
    return null;
  } catch (err) {
    console.warn('Failed to read local current_edition.json:', err.message);
    return null;
  }
}

export async function getEdition(editionId) {
  if (!editionId) return null;
  const remoteBase = process.env.EDITIONS_BASE_URL;
  if (remoteBase) {
    const baseUrl = remoteBase.replace(/\/$/, '');
    const remoteUrls = [
      `${baseUrl}/editions/${encodeURIComponent(editionId)}.json`,
      `${baseUrl}/${encodeURIComponent(editionId)}.json`,
    ];
    for (const url of remoteUrls) {
      try {
        const res = await fetch(url, { cache: 'force-cache' });
        if (res.ok) {
          return await res.json();
        }
      } catch (err) {
        console.warn(`Failed to fetch remote edition from ${url}:`, err.message);
      }
    }
    return null;
  }

  // Local file read
  try {
    const dir = getEditionsDirPath();
    if (!dir || !fs.existsSync(dir)) {
      return null;
    }
    const filePath = path.join(dir, `${editionId}.json`);
    if (!fs.existsSync(filePath)) return null;
    const raw = fs.readFileSync(filePath, 'utf8');
    return JSON.parse(raw);
  } catch (err) {
    console.warn(`Failed to read local edition ${editionId}:`, err.message);
    return null;
  }
}

export async function getCurrentEdition() {
  const pointer = await getCurrentPointer();
  if (!pointer || !pointer.edition_id) return null;
  return await getEdition(pointer.edition_id);
}
