const configuredBase = import.meta.env.VITE_API_BASE || '/api';
// Production always uses the same-origin Vercel/Nginx /api proxy. This also
// prevents a stale Vercel VITE_API_BASE setting from bypassing the proxy and
// causing browser CORS failures. VITE_API_BASE is honored only in dev.
const API_BASE = (import.meta.env.DEV ? configuredBase : '/api').replace(/\/+$/, '');

async function readResponse(response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    const looksLikeHtml = /<!doctype html|<html[\s>]|<title>/i.test(text);
    return {
      message: looksLikeHtml
        ? 'The backend returned an HTML error page instead of JSON. Check the backend deployment and server logs.'
        : text.slice(0, 500) || 'The server returned a non-JSON response.',
    };
  }
}

async function request(endpoint, options = {}) {
  const url = API_BASE + endpoint;
  const headers = new Headers(options.headers || {});
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  if (options.body && !isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  // Prevent a stalled API request from leaving the page in a permanent
  // loading state. Refresh gets a longer budget because it fetches historical
  // publication windows from Elexon.
  const timeoutMs = options.timeoutMs ?? 25000;
  const fetchOptions = { ...options };
  delete fetchOptions.timeoutMs;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, { ...fetchOptions, headers, signal: controller.signal });
    const data = await readResponse(response);
    if (!response.ok) {
      throw new Error(data?.message || data?.error || 'HTTP ' + response.status + ' from ' + endpoint);
    }
    if (data === null) throw new Error('The server returned an empty response for ' + endpoint);
    return data;
  } catch (error) {
    const message = error?.name === 'AbortError'
      ? 'Request timed out after ' + Math.ceil(timeoutMs / 1000) + ' seconds for ' + endpoint + '.'
      : error.message;
    console.error('API request failed: ' + endpoint, error);
    throw new Error(message || ('Request failed for ' + endpoint));
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export const api = {
  health: () => request('/health'),

  summary: (month = '2026-01') => request(`/summary?month=${encodeURIComponent(month)}`),

  forecasts: (start, end) => request(`/forecasts?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`),

  accuracy: (month = '2026-01') => request(`/accuracy?month=${encodeURIComponent(month)}`),

  intervals: (start, end, page = 1, pageSize = 50) =>
    request(`/intervals?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&page=${page}&page_size=${pageSize}`),

  exportIntervals: async (start, end) => {
    const response = await fetch(`${API_BASE}/intervals/export?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
    if (!response.ok) {
      const data = await readResponse(response);
      throw new Error(data?.message || data?.error || `CSV export failed (HTTP ${response.status})`);
    }
    return response.blob();
  },

  refresh: async (startDate = '2026-01-01', endDate = '2026-02-01') => {
    // The initial request returns a job ID immediately. Poll the cheap status
    // endpoint while the backend fetches the full historic Elexon publication window.
    const started = await request('/refresh', {
      method: 'POST',
      timeoutMs: 20000,
      body: JSON.stringify({ start_date: startDate, end_date: endDate }),
    });

    // Backwards compatibility if an older backend still returns a completed result.
    if (started.status === 'success') return started;
    if (started.status !== 'started' || !started.refresh_id) {
      throw new Error(started.message || 'The backend did not start the refresh job.');
    }

    const deadline = Date.now() + 8 * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise(resolve => window.setTimeout(resolve, 2000));
      const job = await request(`/refresh/status/${encodeURIComponent(started.refresh_id)}`);
      if (job.status === 'completed') {
        return { status: 'success', stats: job.stats || {} };
      }
      if (job.status === 'failed' || job.status === 'error') {
        throw new Error(job.message || 'The Elexon refresh failed. Check the backend refresh status and logs.');
      }
    }

    throw new Error('The refresh is still running. Wait a moment, then refresh the dashboard to see whether it completed.');
  },

  import: (actualFile, forecastFile, startDate = '2026-01-01', endDate = '2026-02-01') => {
    const formData = new FormData();
    formData.append('actual_file', actualFile);
    formData.append('forecast_file', forecastFile);
    formData.append('start_date', startDate);
    formData.append('end_date', endDate);
    return request('/import', { method: 'POST', timeoutMs: 120000, body: formData });
  },
};

export function formatDateTime(isoString) {
  if (!isoString) return '—';
  try {
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) return isoString;
    return date.toLocaleString('en-GB', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Europe/London',
      hour12: false,
    });
  } catch {
    return isoString;
  }
}

export function formatDate(isoString) {
  if (!isoString) return '—';
  try {
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) return isoString;
    return date.toLocaleDateString('en-GB', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      timeZone: 'Europe/London',
    });
  } catch {
    return isoString;
  }
}

export function formatNumber(value, decimals = 0) {
  if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return '—';
  return Number(value).toLocaleString('en-GB', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatMW(value) {
  const formatted = formatNumber(value, 1);
  return formatted === '—' ? formatted : `${formatted} MW`;
}

export function formatPercent(value) {
  if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return '—';
  return `${Number(value).toFixed(2)}%`;
}
