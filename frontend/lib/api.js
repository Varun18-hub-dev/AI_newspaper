/**
 * API client for the Personalized AI Newspaper REST API.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';

export async function fetchHealth() {
  const res = await fetch(`${API_BASE_URL}/api/health`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Health check failed: ${res.statusText}`);
  return res.json();
}

export async function fetchDomains() {
  const res = await fetch(`${API_BASE_URL}/api/domains`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Failed to fetch domains: ${res.statusText}`);
  return res.json();
}

export async function fetchLatestStories({ domain = null, topic = null, page = 1, pageSize = 12 } = {}) {
  const params = new URLSearchParams();
  if (domain && domain !== 'all') params.append('domain', domain);
  if (topic && topic !== 'all') params.append('topic', topic);
  params.append('page', page);
  params.append('page_size', pageSize);

  const res = await fetch(`${API_BASE_URL}/api/newspaper/latest?${params.toString()}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Failed to fetch stories: ${res.statusText}`);
  return res.json();
}

export async function fetchStoryDetail(clusterId) {
  const res = await fetch(`${API_BASE_URL}/api/newspaper/stories/${encodeURIComponent(clusterId)}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Failed to fetch story details: ${res.statusText}`);
  return res.json();
}

export async function fetchLatestRun() {
  const res = await fetch(`${API_BASE_URL}/api/runs/latest`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Failed to fetch latest run: ${res.statusText}`);
  return res.json();
}

export async function fetchRecentRuns(limit = 10) {
  const res = await fetch(`${API_BASE_URL}/api/runs?limit=${limit}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Failed to fetch runs: ${res.statusText}`);
  return res.json();
}

export async function triggerManualRefresh(domains = null) {
  const url = domains ? `${API_BASE_URL}/api/runs/refresh?domains=${encodeURIComponent(domains)}` : `${API_BASE_URL}/api/runs/refresh`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (res.status === 409) {
    const errorData = await res.json();
    const err = new Error(errorData.detail || 'A pipeline run is already currently active.');
    err.status = 409;
    throw err;
  }
  if (!res.ok && res.status !== 202) {
    throw new Error(`Failed to trigger refresh: ${res.statusText}`);
  }
  return res.json();
}
