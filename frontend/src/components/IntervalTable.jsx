import React from 'react';
import { formatDateTime, formatMW, formatNumber } from '../services/api';

export function IntervalTable({ 
  data, 
  pagination, 
  onPageChange, 
  onExport,
  loading 
}) {
  if (loading) {
    return (
      <div className="table-container">
        <div className="loading">
          <div className="loading-spinner" />
        </div>
      </div>
    );
  }

  if (!data?.length) {
    return (
      <div className="table-container">
        <div className="empty-state" style={{ height: 300 }}>
          <div className="empty-state-icon">📋</div>
          <div className="empty-state-title">No interval data</div>
          <div className="empty-state-message">
            No evaluation records found for the selected period.
          </div>
        </div>
      </div>
    );
  }

  const getStatusClass = (status) => {
    switch (status) {
      case 'evaluated': return 'status-evaluated';
      case 'missing_actual':
      case 'missing_forecast': return 'status-missing';
      default: return '';
    }
  };

  const getStatusLabel = (status) => {
    switch (status) {
      case 'evaluated': return '✓ Evaluated';
      case 'missing_actual': return '✗ Missing Actual';
      case 'missing_forecast': return '✗ Missing Forecast';
      default: return status;
    }
  };

  const getErrorClass = (error) => {
    if (error === null || error === undefined) return '';
    return error > 0 ? 'error-positive' : error < 0 ? 'error-negative' : '';
  };

  return (
    <div className="table-container">
      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              <th>Delivery Interval (UK)</th>
              <th>Actual (MW)</th>
              <th>Forecast (MW)</th>
              <th>Forecast Published (UK)</th>
              <th>Signed Error (MW)</th>
              <th>Absolute Error (MW)</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {data.map((row, index) => (
              <tr key={index}>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>
                  {formatDateTime(row.start_time_utc)}
                </td>
                <td style={{ fontFamily: 'var(--font-mono)' }}>
                  {row.actual_generation_mw !== null && row.actual_generation_mw !== undefined 
                    ? formatMW(row.actual_generation_mw) 
                    : '—'}
                </td>
                <td style={{ fontFamily: 'var(--font-mono)' }}>
                  {row.selected_forecast_generation_mw !== null && row.selected_forecast_generation_mw !== undefined 
                    ? formatMW(row.selected_forecast_generation_mw) 
                    : '—'}
                </td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>
                  {formatDateTime(row.selected_forecast_publish_time_utc)}
                </td>
                <td className={getErrorClass(row.error_mw)} style={{ fontFamily: 'var(--font-mono)', fontWeight: 500 }}>
                  {row.error_mw !== null && row.error_mw !== undefined 
                    ? (row.error_mw > 0 ? '+' : '') + formatMW(row.error_mw) 
                    : '—'}
                </td>
                <td style={{ fontFamily: 'var(--font-mono)' }}>
                  {row.absolute_error_mw !== null && row.absolute_error_mw !== undefined 
                    ? formatMW(row.absolute_error_mw) 
                    : '—'}
                </td>
                <td className={getStatusClass(row.evaluation_status)}>
                  {getStatusLabel(row.evaluation_status)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pagination">
        <div className="pagination-info">
          Showing {((pagination.page - 1) * pagination.page_size) + 1} to {Math.min(pagination.page * pagination.page_size, pagination.total)} of {pagination.total} intervals
        </div>
        <div className="pagination-controls">
          <button
            className="btn btn-secondary btn-icon"
            onClick={() => onPageChange(1)}
            disabled={pagination.page === 1}
            aria-label="First page"
          >
            ««
          </button>
          <button
            className="btn btn-secondary btn-icon"
            onClick={() => onPageChange(pagination.page - 1)}
            disabled={pagination.page === 1}
            aria-label="Previous page"
          >
            «
          </button>
          <span style={{ padding: '0 8px', fontSize: '0.875rem', color: '#424242' }}>
            Page {pagination.page} of {pagination.total_pages}
          </span>
          <button
            className="btn btn-secondary btn-icon"
            onClick={() => onPageChange(pagination.page + 1)}
            disabled={pagination.page >= pagination.total_pages}
            aria-label="Next page"
          >
            »
          </button>
          <button
            className="btn btn-secondary btn-icon"
            onClick={() => onPageChange(pagination.total_pages)}
            disabled={pagination.page >= pagination.total_pages}
            aria-label="Last page"
          >
            »»
          </button>
          <button
            className="btn btn-primary"
            onClick={onExport}
            disabled={loading}
          >
            📥 Export CSV
          </button>
        </div>
      </div>
    </div>
  );
}