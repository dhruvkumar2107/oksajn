const API_BASE = 'https://oksajn.onrender.com/api';

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
    // Keep each request short enough for the hosting proxy. In-process job IDs
    // are unreliable when a web host restarts or routes polls across instances.
    const start = new Date(`${startDate}T00:00:00Z`);
    const end = new Date(`${endDate}T00:00:00Z`);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end <= start) {
      throw new Error('Refresh dates are invalid. Check the selected start and end dates.');
    }

    const chunkDays = 7;
    const totals = {
      actual_records: 0,
      forecast_records: 0,
      eligible_forecasts: 0,
      matched_intervals: 0,
      unmatched_intervals: 0,
      errors: [],
      chunks_completed: 0,
      chunks_total: Math.ceil((end.getTime() - start.getTime()) / (chunkDays * 86400000)),
    };
    let cursor = start.getTime();

    while (cursor < end.getTime()) {
      const next = Math.min(cursor + chunkDays * 86400000, end.getTime());
      const chunkStart = new Date(cursor).toISOString().slice(0, 10);
      const chunkEnd = new Date(next).toISOString().slice(0, 10);
      const result = await request('/refresh', {
        method: 'POST',
        timeoutMs: 100000,
        body: JSON.stringify({ start_date: chunkStart, end_date: chunkEnd }),
      });
      if (result.status !== 'success') {
        throw new Error(result.message || `Elexon refresh failed for ${chunkStart} to ${chunkEnd}.`);
      }

      const stats = result.stats || {};
      for (const key of ['actual_records', 'forecast_records', 'eligible_forecasts', 'matched_intervals', 'unmatched_intervals']) {
        totals[key] += Number(stats[key] || 0);
      }
      if (Array.isArray(stats.errors)) totals.errors.push(...stats.errors);
      totals.chunks_completed += 1;
      cursor = next;
    }

    return { status: 'success', stats: totals };
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
