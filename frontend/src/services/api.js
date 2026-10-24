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
    return { message: text.slice(0, 500) || 'The server returned a non-JSON response.' };
  }
}

async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const headers = new Headers(options.headers || {});
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  if (options.body && !isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  try {
    const response = await fetch(url, { ...options, headers });
    const data = await readResponse(response);
    if (!response.ok) {
      throw new Error(data?.message || data?.error || `HTTP ${response.status} from ${endpoint}`);
    }
    if (data === null) throw new Error(`The server returned an empty response for ${endpoint}`);
    return data;
  } catch (error) {
    console.error(`API request failed: ${endpoint}`, error);
    throw error;
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

  refresh: (startDate = '2026-01-01', endDate = '2026-02-01') =>
    request('/refresh', {
      method: 'POST',
      body: JSON.stringify({ start_date: startDate, end_date: endDate }),
    }),

  import: (actualFile, forecastFile, startDate = '2026-01-01', endDate = '2026-02-01') => {
    const formData = new FormData();
    formData.append('actual_file', actualFile);
    formData.append('forecast_file', forecastFile);
    formData.append('start_date', startDate);
    formData.append('end_date', endDate);
    return request('/import', { method: 'POST', body: formData });
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
