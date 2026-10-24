import React, { useState, useEffect, useCallback } from 'react';
import { api, formatDate, formatMW, formatNumber, formatPercent } from './services/api';
import { KPICard, OverviewCards, MetricExplanationCard } from './components/KPICards';
import { ForecastVsActualChart, ErrorChart, DailyErrorChart } from './components/Charts';
import { IntervalTable } from './components/IntervalTable';

function App() {
  const [summary, setSummary] = useState(null);
  const [accuracy, setAccuracy] = useState(null);
  const [forecastData, setForecastData] = useState([]);
  const [intervalData, setIntervalData] = useState([]);
  const [intervalPagination, setIntervalPagination] = useState({ page: 1, page_size: 50, total: 0, total_pages: 0 });
  const [lastRefresh, setLastRefresh] = useState(null);
  const [loading, setLoading] = useState({ summary: true, accuracy: true, forecasts: true, intervals: true });
  const [errors, setErrors] = useState({});
  const [dateRange, setDateRange] = useState({ start: '2026-01-01', end: '2026-02-01' });
  const [intervalPage, setIntervalPage] = useState(1);
  const [warnings, setWarnings] = useState([]);
  const [actualImportFile, setActualImportFile] = useState(null);
  const [forecastImportFile, setForecastImportFile] = useState(null);
  const [importMessage, setImportMessage] = useState("");

  const fetchSummary = useCallback(async () => {
    try {
      setLoading(prev => ({ ...prev, summary: true }));
      const data = await api.summary('2026-01');
      setSummary(data);
      setErrors(prev => { const next = { ...prev }; delete next.summary; return next; });
      setWarnings(data.data_quality?.warnings || []);
      setLastRefresh(data.data_quality?.last_refresh || null);
    } catch (err) {
      setErrors(prev => ({ ...prev, summary: err.message }));
    } finally {
      setLoading(prev => ({ ...prev, summary: false }));
    }
  }, []);

  const fetchAccuracy = useCallback(async () => {
    try {
      setLoading(prev => ({ ...prev, accuracy: true }));
      const data = await api.accuracy('2026-01');
      setAccuracy(data);
      setErrors(prev => { const next = { ...prev }; delete next.accuracy; return next; });
    } catch (err) {
      setErrors(prev => ({ ...prev, accuracy: err.message }));
    } finally {
      setLoading(prev => ({ ...prev, accuracy: false }));
    }
  }, []);

  const fetchForecasts = useCallback(async () => {
    try {
      setLoading(prev => ({ ...prev, forecasts: true }));
      const data = await api.forecasts(dateRange.start, dateRange.end);
      setForecastData(data.data || []);
      setErrors(prev => { const next = { ...prev }; delete next.forecasts; return next; });
    } catch (err) {
      setErrors(prev => ({ ...prev, forecasts: err.message }));
    } finally {
      setLoading(prev => ({ ...prev, forecasts: false }));
    }
  }, [dateRange.start, dateRange.end]);

  const fetchIntervals = useCallback(async (page = 1) => {
    try {
      setLoading(prev => ({ ...prev, intervals: true }));
      const data = await api.intervals(dateRange.start, dateRange.end, page, 50);
      setIntervalData(data.data || []);
      setIntervalPagination(data.pagination);
      setIntervalPage(page);
      setErrors(prev => { const next = { ...prev }; delete next.intervals; return next; });
    } catch (err) {
      setErrors(prev => ({ ...prev, intervals: err.message }));
    } finally {
      setLoading(prev => ({ ...prev, intervals: false }));
    }
  }, [dateRange.start, dateRange.end]);

  const handleRefresh = async () => {
    setErrors(prev => { const next = { ...prev }; delete next.refresh; return next; });
    setImportMessage("");
    try {
      setLoading(prev => ({ ...prev, summary: true, accuracy: true, forecasts: true, intervals: true }));
      const result = await api.refresh('2026-01-01', '2026-02-01');
      if (result.status === 'success') {
        setErrors(prev => { const next = { ...prev }; delete next.refresh; return next; });
        await fetchSummary();
        await fetchAccuracy();
        await fetchForecasts();
        await fetchIntervals(1);
      } else {
        setErrors(prev => ({ ...prev, refresh: result.message || 'Refresh failed. Check the backend status.' }));
      }
    } catch (err) {
      setErrors(prev => ({ ...prev, refresh: err.message }));
    } finally {
      setLoading(prev => ({ ...prev, summary: false, accuracy: false, forecasts: false, intervals: false }));
    }
  };

  const handleImport = async () => {
    if (!actualImportFile || !forecastImportFile) {
      setErrors(prev => ({ ...prev, import: 'Select both the FUELHH WIND actuals JSON and the WINDFOR forecasts JSON files first.' }));
      return;
    }

    setErrors(prev => { const next = { ...prev }; delete next.import; return next; });
    setImportMessage("");
    try {
      setLoading(prev => ({ ...prev, summary: true, accuracy: true, forecasts: true, intervals: true }));
      const result = await api.import(actualImportFile, forecastImportFile, '2026-01-01', '2026-02-01');
      if (result.status === 'success') {
        const stats = result.stats || {};
        setImportMessage(`Imported ${stats.actual_records ?? 0} actual records and ${stats.forecast_records ?? 0} forecast records; ${stats.matched_intervals ?? 0} intervals matched.`);
        setActualImportFile(null);
        setForecastImportFile(null);
        await fetchSummary();
        await fetchAccuracy();
        await fetchForecasts();
        await fetchIntervals(1);
      } else {
        setErrors(prev => ({ ...prev, import: result.message || 'Import failed. Check the files and backend logs.' }));
      }
    } catch (err) {
      setErrors(prev => ({ ...prev, import: err.message }));
    } finally {
      setLoading(prev => ({ ...prev, summary: false, accuracy: false, forecasts: false, intervals: false }));
    }
  };

  const handleExport = async () => {
    try {
      const blob = await api.exportIntervals(dateRange.start, dateRange.end);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `wind_forecast_evaluation_${dateRange.start}_to_${dateRange.end}.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      setErrors(prev => ({ ...prev, export: err.message }));
    }
  };

  useEffect(() => {
    fetchSummary();
    fetchAccuracy();
  }, [fetchSummary, fetchAccuracy]);

  useEffect(() => {
    fetchForecasts();
    fetchIntervals(1);
  }, [fetchForecasts, fetchIntervals]);

  const isLoading = Object.values(loading).some(v => v);

  return (
    <div className="app">
      <header className="header">
        <div className="header-content">
          <div>
            <h1 className="header-title">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 18V5l12-2v13" />
                <circle cx="6" cy="18" r="3" />
                <circle cx="18" cy="16" r="3" />
              </svg>
              WindSight
            </h1>
            <p className="header-subtitle">Day-Ahead Wind Forecast Analytics | UK Electricity Market</p>
          </div>
          <div className="header-actions">
            <div className="file-pickers">
              <label htmlFor="actual-file-input" className="btn btn-secondary">
                {actualImportFile ? 'Actuals selected ✓' : 'Choose actuals JSON'}
              </label>
              <input
                type="file"
                id="actual-file-input"
                accept=".json,application/json"
                onChange={event => setActualImportFile(event.target.files?.[0] || null)}
                className="visually-hidden-file"
              />
              <label htmlFor="forecast-file-input" className="btn btn-secondary">
                {forecastImportFile ? 'Forecasts selected ✓' : 'Choose forecasts JSON'}
              </label>
              <input
                type="file"
                id="forecast-file-input"
                accept=".json,application/json"
                onChange={event => setForecastImportFile(event.target.files?.[0] || null)}
                className="visually-hidden-file"
              />
            </div>
            <button className="btn btn-primary" onClick={handleImport}
              disabled={!actualImportFile || !forecastImportFile || isLoading}>
              Import historical data
            </button>
            <button className="btn btn-secondary" onClick={handleRefresh} disabled={isLoading}>
              Refresh from Elexon
            </button>
          </div>
        </div>
      </header>

      <main className="main">
        <div>
          <h1 className="page-title">Executive Overview — January 2026</h1>
          <p className="page-description">
            Wind generation forecast accuracy for day-ahead procurement decisions. 
            Evaluation uses the latest eligible forecast published at or before 11:00 UK time on the day before delivery.
          </p>
        </div>

        {importMessage && (
          <div className="alert alert-info" role="status">{importMessage}</div>
        )}

        {Object.keys(errors).length > 0 && (
          <div style={{ marginBottom: '24px' }}>
            {Object.entries(errors).map(([key, message]) => (
              <div key={key} className="alert alert-error">
                <strong>{key}:</strong> {message}
              </div>
            ))}
          </div>
        )}

        {warnings.length > 0 && (
          <div style={{ marginBottom: '24px' }}>
            {warnings.map((w, i) => (
              <div key={i} className="alert alert-warning">
                ⚠ {w}
              </div>
            ))}
          </div>
        )}

        <section className="section">
          <h2 className="section-title">Key Accuracy Metrics</h2>
          <OverviewCards summary={summary} accuracy={accuracy} lastRefresh={lastRefresh} />
        </section>

        <section className="section">
          <h2 className="section-title">Forecast vs Actual Wind Generation</h2>
          <ForecastVsActualChart data={forecastData} height={450} />
        </section>

        <section className="section">
          <h2 className="section-title">Forecast Error Analysis</h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
            <ErrorChart data={forecastData} height={350} />
            <DailyErrorChart data={forecastData} height={350} />
          </div>
        </section>

        <section className="section">
          <h2 className="section-title">Accuracy Metrics Explained</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(350px, 1fr))', gap: '16px' }}>
            {accuracy?.metrics && Object.entries(accuracy.metrics).map(([key, metric]) => (
              <MetricExplanationCard
                key={key}
                metric={{
                  name: key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
                  value: metric.value,
                  unit: key.includes('mape') ? '%' : 'MW',
                  sample_count: metric.sample_count,
                  description: metric.description,
                  formula: key === 'mae_mw' ? 'MAE = mean(|forecast - actual|)' :
                           key === 'rmse_mw' ? 'RMSE = sqrt(mean((forecast - actual)²))' :
                           key === 'bias_mw' ? 'Bias = mean(forecast - actual)' :
                           key === 'mape_percent' ? 'MAPE = mean(|forecast - actual| / |actual|) × 100 (excl. near-zero actuals)' :
                           'Coverage = matched / total intervals',
                  caveat: metric.caveat || 'These metrics evaluate wind forecast accuracy only. They do not determine optimal procurement quantities.'
                }}
              />
            ))}
          </div>
        </section>

        <section className="section">
          <h2 className="section-title">Interval-Level Audit Table</h2>
          <div className="filters">
            <div className="filter-group">
              <label className="filter-label">Period Start</label>
              <input
                type="date"
                className="filter-input"
                value={dateRange.start}
                onChange={e => setDateRange(prev => ({ ...prev, start: e.target.value }))}
              />
            </div>
            <div className="filter-group">
              <label className="filter-label">Period End</label>
              <input
                type="date"
                className="filter-input"
                value={dateRange.end}
                onChange={e => setDateRange(prev => ({ ...prev, end: e.target.value }))}
              />
            </div>
            <button
              className="btn btn-secondary"
              onClick={() => fetchIntervals(1)}
              disabled={loading.intervals}
            >
              Apply Filter
            </button>
          </div>
          <IntervalTable
            data={intervalData}
            pagination={intervalPagination}
            onPageChange={fetchIntervals}
            onExport={handleExport}
            loading={loading.intervals}
          />
        </section>
      </main>

      <footer className="footer">
        WindSight Day-Ahead Analytics Pilot — Built for UK electricity procurement teams.
        Data source: Elexon BMRS FUELHH & WINDFOR datasets. 
        Forecast selection: latest eligible forecast published at or before 11:00 UK time (D-1).
        Not for operational use without validation.
      </footer>
    </div>
  );
}

export default App;