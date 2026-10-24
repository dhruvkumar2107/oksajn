import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  AreaChart,
  Area,
} from 'recharts';

const COLORS = {
  actual: '#1B2A4A',
  forecast: '#2E7D32',
  error: '#C62828',
  zero: '#9E9E9E',
};

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  
  const date = new Date(label);
  const formattedDate = date.toLocaleString('en-GB', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/London',
    hour12: false,
  });

  return (
    <div style={{
      background: 'white',
      border: '1px solid #E0E0E0',
      borderRadius: '8px',
      padding: '12px 16px',
      boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
      minWidth: 200,
    }}>
      <div style={{ fontWeight: 600, color: '#1B2A4A', marginBottom: 8 }}>{formattedDate}</div>
      {payload.map((entry, index) => (
        <div key={index} style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 4,
          color: entry.color,
        }}>
          <span style={{
            width: 10,
            height: 10,
            borderRadius: 2,
            background: entry.color,
          }} />
          <span>{entry.name}: </span>
          <span style={{ fontWeight: 500 }}>
            {entry.value !== null && entry.value !== undefined 
              ? entry.value.toLocaleString('en-GB', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + ' MW'
              : '—'}
          </span>
        </div>
      ))}
    </div>
  );
}

export function ForecastVsActualChart({ data, height = 400 }) {
  if (!data?.length) {
    return (
      <div className="chart-container" style={{ height }}>
        <div className="empty-state" style={{ height: '100%' }}>
          <div className="empty-state-icon">📈</div>
          <div className="empty-state-title">No forecast data available</div>
          <div className="empty-state-message">
            Import historical data or check the selected date range.
          </div>
        </div>
      </div>
    );
  }

  const chartData = data.map(d => ({
    time: d.start_time_utc,
    actual: d.actual_generation_mw,
    forecast: d.selected_forecast_generation_mw,
    forecastPublishTime: d.selected_forecast_publish_time_utc,
  }));

  return (
    <div className="chart-container" style={{ height }}>
      <div className="chart-title">Wind Generation: Actual vs Decision-Eligible Forecast</div>
      <div className="legend">
        <div className="legend-item">
          <span className="legend-color" style={{ background: COLORS.actual }} />
          <span>Actual Wind Generation</span>
        </div>
        <div className="legend-item">
          <span className="legend-color" style={{ background: COLORS.forecast }} />
          <span>Decision-Eligible Forecast</span>
        </div>
      </div>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="actualGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={COLORS.actual} stopOpacity={0.3} />
              <stop offset="95%" stopColor={COLORS.actual} stopOpacity={0} />
            </linearGradient>
            <linearGradient id="forecastGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={COLORS.forecast} stopOpacity={0.2} />
              <stop offset="95%" stopColor={COLORS.forecast} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#E0E0E0" vertical={false} />
          <XAxis
            dataKey="time"
            tickFormatter={(value) => new Date(value).toLocaleString('en-GB', {
              month: 'short',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
              timeZone: 'Europe/London',
              hour12: false,
            })}
            tick={{ fontSize: 11, fill: '#757575' }}
            axisLine={{ stroke: '#E0E0E0' }}
            tickLine={{ stroke: '#E0E0E0' }}
            interval="preserveStartEnd"
          />
          <YAxis
            tickFormatter={(value) => value.toLocaleString('en-GB') + ' MW'}
            tick={{ fontSize: 11, fill: '#757575' }}
            axisLine={{ stroke: '#E0E0E0' }}
            tickLine={{ stroke: '#E0E0E0' }}
            label={{ value: 'Generation (MW)', angle: -90, position: 'insideLeft', offset: -10, fill: '#757575', fontSize: 11 }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend />
          <Area
            type="monotone"
            dataKey="actual"
            stroke={COLORS.actual}
            fillOpacity={0.3}
            fill="url(#actualGradient)"
            strokeWidth={2}
            name="Actual Wind Generation"
          />
          <Area
            type="monotone"
            dataKey="forecast"
            stroke={COLORS.forecast}
            fillOpacity={0.2}
            fill="url(#forecastGradient)"
            strokeWidth={2}
            strokeDasharray="5 5"
            name="Decision-Eligible Forecast"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ErrorChart({ data, height = 300 }) {
  if (!data?.length) {
    return (
      <div className="chart-container" style={{ height }}>
        <div className="empty-state" style={{ height: '100%' }}>
          <div className="empty-state-icon">📉</div>
          <div className="empty-state-title">No error data available</div>
          <div className="empty-state-message">
            Import historical data or check the selected date range.
          </div>
        </div>
      </div>
    );
  }

  const chartData = data.map(d => ({
    time: d.start_time_utc,
    error: d.error_mw,
    errorPositive: d.error_mw !== null && d.error_mw !== undefined && d.error_mw >= 0 ? d.error_mw : null,
    errorNegative: d.error_mw !== null && d.error_mw !== undefined && d.error_mw < 0 ? d.error_mw : null,
    absoluteError: d.absolute_error_mw,
    status: d.evaluation_status,
  }));

  const hasData = chartData.some(d => d.error !== null && d.error !== undefined);

  if (!hasData) {
    return (
      <div className="chart-container" style={{ height }}>
        <div className="empty-state" style={{ height: '100%' }}>
          <div className="empty-state-icon">📉</div>
          <div className="empty-state-title">No matched intervals</div>
          <div className="empty-state-message">
            No intervals have both actual and eligible forecast data.
          </div>
        </div>
      </div>
    );
  }

  const maxAbsError = Math.max(1, ...chartData
    .filter(d => d.error !== null && d.error !== undefined)
    .map(d => Math.abs(d.error)));

  return (
    <div className="chart-container" style={{ height }}>
      <div className="chart-title">Forecast Error (Signed MW)</div>
      <div className="legend">
        <div className="legend-item">
          <span className="legend-color" style={{ background: COLORS.error }} />
          <span>Overestimation (+)</span>
        </div>
        <div className="legend-item">
          <span className="legend-color" style={{ background: COLORS.forecast }} />
          <span>Underestimation (-)</span>
        </div>
        <div className="legend-item">
          <span style={{ width: 12, height: 2, background: COLORS.zero, borderRadius: 1, display: 'inline-block' }} />
          <span>Zero Error Line</span>
        </div>
      </div>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#E0E0E0" vertical={false} />
          <XAxis
            dataKey="time"
            tickFormatter={(value) => new Date(value).toLocaleString('en-GB', {
              month: 'short',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
              timeZone: 'Europe/London',
              hour12: false,
            })}
            tick={{ fontSize: 11, fill: '#757575' }}
            axisLine={{ stroke: '#E0E0E0' }}
            tickLine={{ stroke: '#E0E0E0' }}
            interval="preserveStartEnd"
          />
          <YAxis
            tickFormatter={(value) => value.toLocaleString('en-GB') + ' MW'}
            tick={{ fontSize: 11, fill: '#757575' }}
            axisLine={{ stroke: '#E0E0E0' }}
            tickLine={{ stroke: '#E0E0E0' }}
            label={{ value: 'Error (MW)', angle: -90, position: 'insideLeft', offset: -10, fill: '#757575', fontSize: 11 }}
            domain={[-maxAbsError * 1.2, maxAbsError * 1.2]}
          />
          <Tooltip content={<CustomTooltip />} />
          <ReferenceLine y={0} stroke={COLORS.zero} strokeDasharray="4 4" />
          <Line
            type="monotone"
            dataKey="errorPositive"
            stroke={COLORS.error}
            strokeWidth={2}
            dot={false}
            name="Overestimation (+)"
            connectNulls={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="errorNegative"
            stroke={COLORS.forecast}
            strokeWidth={2}
            dot={false}
            name="Underestimation (-)"
            connectNulls={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DailyErrorChart({ data, height = 300 }) {
  if (!data?.length) {
    return (
      <div className="chart-container" style={{ height }}>
        <div className="empty-state" style={{ height: '100%' }}>
          <div className="empty-state-icon">📊</div>
          <div className="empty-state-title">No daily summary available</div>
        </div>
      </div>
    );
  }

  const dailyMap = new Map();
  data.forEach(d => {
    if (d.error_mw === null || d.error_mw === undefined) return;
    const date = new Date(d.start_time_utc).toISOString().split('T')[0];
    if (!dailyMap.has(date)) {
      dailyMap.set(date, { date, errors: [], count: 0 });
    }
    const entry = dailyMap.get(date);
    entry.errors.push(d.error_mw);
    entry.count++;
  });

  const dailyData = Array.from(dailyMap.values()).map(d => ({
    date: d.date,
    mae: d.errors.reduce((a, b) => a + Math.abs(b), 0) / d.errors.length,
    bias: d.errors.reduce((a, b) => a + b, 0) / d.errors.length,
    count: d.count,
  })).sort((a, b) => a.date.localeCompare(b.date));

  return (
    <div className="chart-container" style={{ height }}>
      <div className="chart-title">Daily Forecast Error Summary</div>
      <div className="legend">
        <div className="legend-item">
          <span className="legend-color" style={{ background: COLORS.error }} />
          <span>Daily MAE (MW)</span>
        </div>
        <div className="legend-item">
          <span className="legend-color" style={{ background: COLORS.forecast }} />
          <span>Daily Bias (MW)</span>
        </div>
      </div>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={dailyData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#E0E0E0" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={(value) => new Date(value).toLocaleDateString('en-GB', {
              month: 'short',
              day: 'numeric',
              timeZone: 'Europe/London',
            })}
            tick={{ fontSize: 11, fill: '#757575' }}
            axisLine={{ stroke: '#E0E0E0' }}
            tickLine={{ stroke: '#E0E0E0' }}
            interval="preserveStartEnd"
          />
          <YAxis
            tickFormatter={(value) => value.toLocaleString('en-GB') + ' MW'}
            tick={{ fontSize: 11, fill: '#757575' }}
            axisLine={{ stroke: '#E0E0E0' }}
            tickLine={{ stroke: '#E0E0E0' }}
            label={{ value: 'Error (MW)', angle: -90, position: 'insideLeft', offset: -10, fill: '#757575', fontSize: 11 }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Line
            type="monotone"
            dataKey="mae"
            stroke={COLORS.error}
            strokeWidth={2}
            dot={{ r: 4, strokeWidth: 2 }}
            name="Daily MAE"
            activeDot={{ r: 6, strokeWidth: 2 }}
          />
          <Line
            type="monotone"
            dataKey="bias"
            stroke={COLORS.forecast}
            strokeWidth={2}
            strokeDasharray="5 5"
            dot={{ r: 4, strokeWidth: 2 }}
            name="Daily Bias"
            activeDot={{ r: 6, strokeWidth: 2 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}