const API_BASE = import.meta.env.VITE_API_BASE || '/api';

async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const config = {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  };

  try {
    const response = await fetch(url, config);
    const data = await response.json();
    
    if (!response.ok) {
      throw new Error(data.message || data.error || `HTTP ${response.status}`);
    }
    
    return data;
  } catch (error) {
    console.error(`API request failed: ${endpoint}`, error);
    throw error;
  }
}

export const api = {
  health: () => request('/health'),
  
  summary: (month = '2026-01') => request(`/summary?month=${month}`),
  
  forecasts: (start, end) => request(`/forecasts?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`),
  
  accuracy: (month = '2026-01') => request(`/accuracy?month=${month}`),
  
  intervals: (start, end, page = 1, pageSize = 50) => 
    request(`/intervals?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&page=${page}&page_size=${pageSize}`),
  
  exportIntervals: (start, end) => {
    const url = `${API_BASE}/intervals/export?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
    return fetch(url).then(res => res.blob());
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
    
    return fetch(`${API_BASE}/import`, {
      method: 'POST',
      body: formData,
    }).then(res => res.json());
  },
};

export function formatDateTime(isoString) {
  if (!isoString) return '—';
  try {
    const date = new Date(isoString);
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
  if (value === null || value === undefined || isNaN(value)) return '—';
  return value.toLocaleString('en-GB', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatMW(value) {
  return formatNumber(value, 1) + ' MW';
}

export function formatPercent(value) {
  if (value === null || value === undefined || isNaN(value)) return '—';
  return value.toFixed(2) + '%';
}