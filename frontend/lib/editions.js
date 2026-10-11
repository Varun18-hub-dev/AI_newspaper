
import fs from 'fs';
import path from 'path';
import { S3Client, GetObjectCommand } from '@aws-sdk/client-s3';

function getEditionsDirPath() {
  if (process.env.EDITIONS_DIR) {
    return path.resolve(process.env.EDITIONS_DIR);
  }

  const candidates = [
    path.join(process.cwd(), 'data', 'editions'),
    path.join(process.cwd(), '..', 'data', 'editions'),
    path.resolve(process.cwd(), '../data/editions'),
  ];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }

  return candidates[0];
}

const bucket = process.env.S3_EDITIONS_BUCKET;

const s3Client = bucket
  ? new S3Client({
      region: process.env.AWS_REGION || 'ap-south-1',
      ...(process.env.AWS_ACCESS_KEY_ID &&
      process.env.AWS_SECRET_ACCESS_KEY
        ? {
            credentials: {
              accessKeyId: process.env.AWS_ACCESS_KEY_ID,
              secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY,
            },
          }
        : {}),
    })
  : null;

async function fetchFromS3(key) {
  if (!s3Client || !bucket) return null;

  try {
    const response = await s3Client.send(
      new GetObjectCommand({
        Bucket: bucket,
        Key: key,
      })
    );

    const body = await response.Body.transformToString('utf-8');
    return JSON.parse(body);
  } catch (err) {
    console.warn(`S3 read failed for ${key}:`, err.message);
    return null;
  }
}

export async function getCurrentPointer() {
  if (s3Client) {
    const pointer = await fetchFromS3('current_edition.json');
    if (pointer) return pointer;
  }

  const remoteBase = process.env.EDITIONS_BASE_URL;

  if (remoteBase) {
    const baseUrl = remoteBase.replace(/\/+$/, '');

    for (const url of [
      `${baseUrl}/current_edition.json`,
      `${baseUrl}/editions/current_edition.json`,
    ]) {
      try {
        const response = await fetch(url, { cache: 'no-store' });
        if (response.ok) return await response.json();
      } catch (err) {
        console.warn('Remote pointer fetch failed:', err.message);
      }
    }

    return null;
  }

  try {
    const dir = getEditionsDirPath();
    if (!fs.existsSync(dir)) return null;

    const pointerPath = path.join(dir, 'current_edition.json');

    if (fs.existsSync(pointerPath)) {
      return JSON.parse(fs.readFileSync(pointerPath, 'utf8'));
    }

    const files = fs
      .readdirSync(dir)
      .filter((file) => file.startsWith('edition_') && file.endsWith('.json'))
      .sort()
      .reverse();

    if (!files.length) return null;

    const manifest = JSON.parse(
      fs.readFileSync(path.join(dir, files[0]), 'utf8')
    );

    return {
      edition_id: manifest.edition_id,
      published_at: manifest.published_at,
      checksum: manifest.checksum,
      total_stories: manifest.total_stories,
      run_id: manifest.run_id,
    };
  } catch (err) {
    console.warn('Local pointer read failed:', err.message);
    return null;
  }
}

export async function getEdition(editionId) {
  if (
    !editionId ||
    typeof editionId !== 'string' ||
    !/^[a-zA-Z0-9_-]+$/.test(editionId)
  ) {
    return null;
  }

  if (s3Client) {
    const edition = await fetchFromS3(`editions/${editionId}.json`);
    if (edition) return edition;
  }

  const remoteBase = process.env.EDITIONS_BASE_URL;

  if (remoteBase) {
    const baseUrl = remoteBase.replace(/\/+$/, '');

    for (const url of [
      `${baseUrl}/editions/${encodeURIComponent(editionId)}.json`,
      `${baseUrl}/${encodeURIComponent(editionId)}.json`,
    ]) {
      try {
        const response = await fetch(url, { cache: 'force-cache' });
        if (response.ok) return await response.json();
      } catch (err) {
        console.warn('Remote edition fetch failed:', err.message);
      }
    }

    return null;
  }

  try {
    const dir = getEditionsDirPath();

    for (const filePath of [
      path.join(dir, 'editions', `${editionId}.json`),
      path.join(dir, `${editionId}.json`),
    ]) {
      if (fs.existsSync(filePath)) {
        return JSON.parse(fs.readFileSync(filePath, 'utf8'));
      }
    }

    return null;
  } catch (err) {
    console.warn(`Local edition read failed for ${editionId}:`, err.message);
    return null;
  }
}

export async function getCurrentEdition() {
  const pointer = await getCurrentPointer();

  if (!pointer?.edition_id) return null;

  return getEdition(pointer.edition_id);
}
