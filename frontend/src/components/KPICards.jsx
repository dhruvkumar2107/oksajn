import React from 'react';
import { formatMW, formatNumber, formatPercent } from '../services/api';

export function KPICard({ title, value, subtitle, variant, unit }) {
  const formattedValue = value === null || value === undefined || isNaN(value) ? '—' : 
    (unit === 'MW' ? formatMW(value) : 
     unit === '%' ? formatPercent(value) : 
     formatNumber(value));

  return (
    <div className="card">
      <div className="card-title">{title}</div>
      <div className={`card-value ${variant || ''}`}>{formattedValue}</div>
      {subtitle && <div className="card-subtitle">{subtitle}</div>}
    </div>
  );
}

export function OverviewCards({ summary, accuracy, lastRefresh }) {
  const metrics = accuracy?.metrics || {};
  const coverage = summary?.coverage || {};
  const dataQuality = summary?.data_quality || {};

  return (
    <div className="card-grid">
      <KPICard
        title="Mean Absolute Error (MAE)"
        value={metrics.mae_mw?.value}
        unit="MW"
        subtitle={`${metrics.mae_mw?.sample_count || 0} matched intervals`}
      />
      <KPICard
        title="Root Mean Squared Error (RMSE)"
        value={metrics.rmse_mw?.value}
        unit="MW"
        subtitle={`Penalizes larger errors more heavily`}
      />
      <KPICard
        title="Mean Bias"
        value={metrics.bias_mw?.value}
        unit="MW"
        variant={metrics.bias_mw?.value > 0 ? 'warning' : metrics.bias_mw?.value < 0 ? 'success' : ''}
        subtitle={metrics.bias_mw?.value > 0 ? 'Systematic overestimation' : metrics.bias_mw?.value < 0 ? 'Systematic underestimation' : 'No systematic bias'}
      />
      <KPICard
        title="MAPE"
        value={metrics.mape_percent?.value}
        unit="%"
        subtitle={`Excludes actuals ≤ ${metrics.mape_percent?.exclusion_threshold_mw || 1} MW • ${metrics.mape_percent?.sample_count || 0} observations`}
      />
      <KPICard
        title="Evaluation Coverage"
        value={coverage.coverage_percent}
        unit="%"
        subtitle={`${coverage.matched_intervals || 0} of ${coverage.total_intervals || 0} intervals matched`}
      />
      <KPICard
        title="Data Last Refreshed"
        value={lastRefresh ? new Date(lastRefresh.completed_at || lastRefresh.started_at).toLocaleString('en-GB') : 'Never'}
        subtitle={lastRefresh?.status === 'completed' ? `Processed ${lastRefresh.records_processed || 0} records` : lastRefresh?.status || 'Unknown'}
      />
    </div>
  );
}

export function MetricExplanationCard({ metric }) {
  return (
    <div className="card" style={{ marginBottom: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
        <div>
          <div className="card-title" style={{ fontSize: '1rem', marginBottom: '4px' }}>{metric.name}</div>
          <div style={{ fontSize: '0.875rem', color: '#424242' }}>{metric.formula}</div>
        </div>
        <div className="card-value" style={{ fontSize: '1.5rem' }}>
          {metric.value !== null && metric.value !== undefined ? 
            (metric.unit === 'MW' ? formatMW(metric.value) : metric.unit === '%' ? formatPercent(metric.value) : formatNumber(metric.value)) 
            : '—'}
        </div>
      </div>
      <div style={{ fontSize: '0.875rem', color: '#757575', marginBottom: '8px' }}>
        <strong>Sample count:</strong> {metric.sample_count || 0}
      </div>
      <div style={{ fontSize: '0.875rem', color: '#757575' }}>
        {metric.description}
      </div>
      {metric.caveat && (
        <div style={{ fontSize: '0.75rem', color: '#9E9E9E', marginTop: '8px', fontStyle: 'italic' }}>
          {metric.caveat}
        </div>
      )}
    </div>
  );
}