# WindSight | Day-Ahead Analytics

A pilot web application for a UK energy utility's day-ahead procurement team. It compares national wind generation actuals with the forecast vintage that was available by a configurable decision cutoff, and calculates forecast-error metrics.

## 📋 Overview

WindSight helps procurement teams at UK electricity utilities understand:
- **Latest eligible national wind forecasts** available at purchasing decision time
- **Forecast accuracy metrics** (MAE, RMSE, Bias, MAPE) when genuine, validated historical records are available
- **Forecast overestimation/underestimation patterns** for risk management
- **Interval-level audit trails** with forecast publication timestamps for transparency

## 🎯 Business Problem

UK electricity utilities buy power on the wholesale day-ahead market (EPEX SPOT, Nord Pool). Wind generation reduces the volume that must be purchased. Procurement teams need to know:
1. How much wind generation is forecast for each delivery interval
2. Which forecast vintage was available when they made purchasing decisions
3. How accurate those forecasts have been historically

WindSight uses only the two official Elexon BMRS datasets specified in the assignment. No other market, weather, or generation data source is used.

## 📊 Data Sources

| Dataset | Elexon Endpoint | Purpose |
|---------|----------------|---------|
| **FUELHH** | `/datasets/FUELHH/stream` | Actual generation; application filters `fuelType=WIND` and uses `startTime` and `generation` |
| **WINDFOR** | `/datasets/WINDFOR/stream` | Forecast generation using `startTime`, `publishTime`, and `generation` |

**Official Documentation:**
- [FUELHH Dataset](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream)
- [WINDFOR Dataset](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream)

## 🛠 Technology Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 18 + Vite 5 |
| Backend | Python 3.11 + Flask 3 |
| Data Processing | Pandas 2 + NumPy 1.26 |
| Charts | Recharts 2 |
| Database | SQLite 3 |
| HTTP Client | Python Requests |
| Testing | pytest 8 + requests-mock |
| Containerization | Docker + Docker Compose |
| Deployment | Vercel (frontend) + Python hosting (backend) |

## 🏗 Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   React UI      │────▶│   Flask API     │────▶│   SQLite DB     │
│   (Port 80)     │     │   (Port 5000)   │     │   (Volume)      │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
            ┌───────────────┐         ┌───────────────┐
            │ Elexon FUELHH │         │ Elexon WINDFOR│
            │   (Actuals)   │         │  (Forecasts)  │
            └───────────────┘         └───────────────┘
```

### Data Flow

1. **Ingestion**: Fetch actuals (FUELHH, filtered to WIND) and forecasts (WINDFOR) from Elexon API
2. **Normalization**: Parse timestamps to UTC, convert to `Europe/London` for cutoff logic
3. **Forecast Selection**: For each delivery interval, select the latest forecast with `publishTime ≤ decision_cutoff`
4. **Evaluation**: Join actuals with selected forecasts, calculate signed errors
5. **Storage**: Persist normalized actuals, forecast vintages, and evaluation results in SQLite
6. **API**: Serve aggregated metrics, time-series data, and paginated interval records
7. **UI**: Render KPI cards, interactive charts, and audit table with CSV export

## 📁 Repository Structure

```
oksajn/
├── backend/
│   ├── app/
│   │   ├── __init__.py          # Flask app factory
│   │   ├── __main__.py          # Local entry point for python -m app
│   │   ├── config.py            # Environment-backed settings
│   │   ├── models/__init__.py   # SQLite schema, migrations & data access
│   │   ├── routes/api.py        # REST API endpoints
│   │   ├── services/
│   │   │   ├── elexon_client.py
│   │   │   └── data_processor.py
│   │   └── tests/
│   │       ├── conftest.py
│   │       ├── test_api_routes.py
│   │       ├── test_data_processor.py
│   │       └── test_elexon_client.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Charts.jsx
│   │   │   ├── KPICards.jsx
│   │   │   └── IntervalTable.jsx
│   │   ├── services/api.js      # API client & formatters
│   │   ├── App.jsx              # Main dashboard
│   │   ├── main.jsx             # Entry point
│   │   └── styles.css           # Design system
│   ├── package.json
│   ├── vite.config.js
│   ├── Dockerfile
│   └── nginx.conf
├── docker-compose.yml
├── docs/VIDEO_DEMO_SCRIPT.md
├── .github/workflows/ci.yml
├── .env.example
├── .dockerignore
├── .gitignore
└── README.md
```

## ⚙️ Forecast Vintage Selection Logic

**Critical Business Rule:** For each delivery interval, select the **latest forecast published at or before the procurement decision cutoff**.

```python
decision_cutoff = delivery_date - 1 day at 11:00 UK time
selected_forecast = max(forecasts.where(publishTime <= decision_cutoff), key=publishTime)
```

### Decision Cutoff Assumption

- **Configured pilot cutoff:** 11:00 UK time on the day before delivery (D-1)
- **Status:** A configurable engineering assumption, not a verified contractual or venue-wide deadline for every GB day-ahead participant.
- **Configuration:** `DECISION_CUTOFF_HOUR`, `DECISION_CUTOFF_MINUTE`, and `DECISION_CUTOFF_TIMEZONE`
- **Timezone:** `Europe/London`; the calculation uses the UK calendar day and local wall-clock time.

**Important:** Confirm the customer's trading venue and actual procurement procedure before relying on this cutoff. A forecast's eligibility is only as correct as the cutoff assumption used. The application must preserve `publishTime` so reviewers can audit eligibility.
### Example

| Delivery Interval | Forecast A Published | Forecast B Published | Forecast C Published | Selected |
|-------------------|---------------------|---------------------|---------------------|----------|
| 2026-01-15 00:00  | 2026-01-14 09:00    | 2026-01-14 10:30    | 2026-01-14 11:30    | **B** (latest ≤ 11:00) |

Forecasts published after the cutoff (e.g., C at 11:30) are **excluded** — they were not available to the buyer.

## 📈 Error Sign Convention

```
error_MW = forecast_generation_MW - actual_generation_MW
```

| Error Sign | Interpretation |
|------------|----------------|
| **Positive** | Wind generation **overestimated** (procurement may have bought too little) |
| **Negative** | Wind generation **underestimated** (procurement may have bought too much) |
| **Zero** | Forecast matched actual |

## 📐 Accuracy Metrics

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| **MAE** | `mean(|forecast - actual|)` | Average absolute error (MW) |
| **RMSE** | `sqrt(mean((forecast - actual)²))` | Penalizes large errors more heavily |
| **Bias** | `mean(forecast - actual)` | Systematic tendency (+ve = overestimation) |
| **MAPE** | `mean(|forecast - actual| / |actual|) × 100` | Percentage error (excludes actuals ≤ 1 MW) |
| **Coverage** | `matched_intervals / intervals_with_actual × 100` | Share of actual delivery intervals that have both actuals and an eligible forecast |

MAE, RMSE, and bias are calculated **only on matched intervals** with both actuals and eligible forecasts. MAPE additionally excludes observations whose absolute actual generation is at or below the configured threshold. Coverage is shown with its numerator and denominator.

## 📅 Historical Data Coverage & Limitations

**Do not assume that the public API is current-only.** The stream endpoints support publication-time filtering. These filters describe when a record was published, not the delivery interval represented by its `startTime`.

- FUELHH actuals: [official stream documentation](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream)
- WINDFOR forecasts: [official stream documentation](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream)
- Historical view of latest wind forecasts: [latest endpoint](https://bmrs.elexon.co.uk/api-documentation/endpoint/forecast/generation/wind/latest) and [latest stream](https://bmrs.elexon.co.uk/api-documentation/endpoint/forecast/generation/wind/latest/stream)
- Historical forecast history: [WINDFOR history endpoint](https://bmrs.elexon.co.uk/api-documentation/endpoint/forecast/generation/wind/history)
- Historical forecast evolution: [WINDFOR evolution endpoint](https://bmrs.elexon.co.uk/api-documentation/endpoint/forecast/generation/wind/evolution)

The application queries the dataset stream endpoints using `publishDateTimeFrom` and `publishDateTimeTo`, then filters returned records to the requested **delivery** period using `startTime`. Requests are split into time windows to keep them bounded.

**Important distinction:** the `/forecast/generation/wind/latest` view supplies the latest forecast for a historical delivery range; by itself it does not prove that every forecast vintage that existed at a past purchasing cutoff is available. This assignment requires the selected forecasts' original `publishTime` values. Check the imported/retrieved record coverage before treating the metrics as a full-period retrospective evaluation.

### Checking January 2026 data

1. Use **Refresh from Elexon** to request the configured January 2026 period.
2. Inspect the returned counts, errors, and the data-quality warnings in the dashboard/backend logs.
3. If the official stream endpoint does not return complete historical data for the required period, obtain genuine Elexon export files from the official [Wind generation page](https://bmrs.elexon.co.uk/wind-generation) or documented historical endpoint and import them.
4. Import an actual FUELHH file containing `startTime`, `generation`, and `fuelType` (WIND rows are enforced) and a WINDFOR file containing `startTime`, `publishTime`, and `generation`. JSON files may be arrays or objects with a `data` array. CSV files need the same source field headers.
5. Confirm that delivery coverage runs from 2026-01-01 inclusive to 2026-02-01 exclusive, then inspect matched and unmatched intervals.

The importer accepts JSON and CSV source exports. It validates the extension and the required record fields; it does not accept arbitrary URLs or filesystem paths. An import that contains no valid records is reported as an error. The application does not manufacture production records or synthetic accuracy results.

Historical data retrieval is considered verified only when real January 2026 records, timestamps, and coverage have been inspected. If publication history cannot be recovered, state that limitation in the demo rather than presenting a later forecast as the forecast available at decision time.

## 🚀 Quick Start

### Prerequisites
- Docker 24+ and Docker Compose 2+
- Or: Python 3.11+, Node 20+

### With Docker (Recommended)

```bash
# Clone and navigate
git clone https://github.com/dhruvkumar2107/oksajn.git
cd oksajn

# Copy environment config
cp .env.example .env

# Build and start
docker compose up --build

# Access
# Frontend: http://localhost
# Backend API: http://localhost:5000/api/health
```

### Without Docker

Open two terminal windows from the repository root.

**Terminal 1 — Backend:**
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp ../.env.example .env    # Windows: copy ..\.env.example .env
python -m app
```

**Terminal 2 — Frontend:**
```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. The Vite dev server proxies `/api` to `http://localhost:5000` by default. Do not start the backend and frontend commands in the same terminal unless you run them as separate processes.

## 🌍 Live Demo

| Service | URL |
|---------|-----|
| **Frontend Dashboard** | https://frontend-95b6.vercel.app |
| **Backend API** | https://oksajn.onrender.com |
| **Health Check** | https://oksajn.onrender.com/api/health |

> **Repository:** This code is hosted in the public repository [dhruvkumar2107/oksajn](https://github.com/dhruvkumar2107/oksajn). The repository name `oksajn` is a non-descriptive, anonymous-style name. Do not create a second repository unless your submission instructions specifically require a different one.

## 🐳 Docker Commands

```bash
# Start services
docker compose up --build

# Stop services
docker compose down

# Stop and remove volumes (resets database)
docker compose down -v

# View logs
docker compose logs -f backend
docker compose logs -f frontend

# Run backend tests in container
docker compose exec backend python -m pytest app/tests/ -v

# Access backend shell
docker compose exec backend bash
```

## 🔧 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `./windsight.db` locally; `/data/windsight.db` in Docker/host config | SQLite database path |
| `ELEXON_BASE_URL` | `https://data.elexon.co.uk/bmrs/api/v1` | Elexon API base |
| `ELEXON_TIMEOUT` | `30` | Request timeout (seconds) |
| `ELEXON_MAX_RETRIES` | `3` | Retry attempts for transient errors |
| `DECISION_CUTOFF_HOUR` | `11` | Procurement cutoff hour (UK) |
| `DECISION_CUTOFF_MINUTE` | `0` | Procurement cutoff minute |
| `DECISION_CUTOFF_TIMEZONE` | `Europe/London` | Cutoff timezone |
| `MAPE_EXCLUSION_THRESHOLD` | `1.0` | MW threshold for MAPE exclusion |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed frontend origins |
| `VITE_API_BASE` | `/api` | Frontend API base URL |

## 📡 API Reference

### Health Check
```
GET /api/health
```

### Summary Metrics
```
GET /api/summary?month=2026-01
```
Returns KPIs, coverage, and data quality warnings.

### Forecast vs Actual Time Series
```
GET /api/forecasts?start=2026-01-01T00:00:00Z&end=2026-02-01T00:00:00Z
```
Returns matched intervals with actual, forecast, error, and forecast publish time.

### Accuracy Metrics Detail
```
GET /api/accuracy?month=2026-01
```
Returns all metrics with formulas, sample counts, and plain-English interpretations.

### Interval Audit Table (Paginated)
```
GET /api/intervals?start=2026-01-01T00:00:00Z&end=2026-02-01T00:00:00Z&page=1&page_size=50
```

### CSV Export
```
GET /api/intervals/export?start=...&end=...
```

### Refresh from Live API
```
POST /api/refresh
Content-Type: application/json
{"start_date": "2026-01-01", "end_date": "2026-02-01"}
```

### Import Historical Data
```
POST /api/import
Content-Type: multipart/form-data
actual_file: <JSON or CSV file>
forecast_file: <JSON or CSV file>
start_date: 2026-01-01
end_date: 2026-02-01
```

## 🧪 Testing

Run the following commands from the repository root:

```bash
# Backend unit and API tests
(cd backend && python -m pytest app/tests/ -v)

# Frontend production build
(cd frontend && npm ci && npm run build)

# Validate and build Docker Compose services
docker compose config
docker compose build
```

GitHub Actions runs the backend test suite, builds the frontend, builds both Docker images, starts the integrated application, and smoke-tests the backend health, Vercel/Nginx-style `/api` proxy route, and January 2026 summary endpoint. See the [latest CI run](https://github.com/dhruvkumar2107/oksajn/actions).

### Test Coverage
- Timestamp parsing & timezone normalization
- WIND-only actual filtering
- Delivery interval matching
- Forecast vintage selection (cutoff logic)
- Duplicate publication handling
- Missing actuals/forecasts
- Error sign convention
- MAE, RMSE, Bias, MAPE calculations
- Empty/zero datasets
- Coverage calculations
- API error handling (timeouts, HTTP errors, invalid JSON)

## 🌐 Deployment

### Live Deployment
- **Frontend (Vercel):** https://frontend-95b6.vercel.app
- **Backend (Render):** https://oksajn.onrender.com
- **API Health:** https://oksajn.onrender.com/api/health

### Frontend → Vercel
1. Connect GitHub repository to Vercel
2. Set **Framework Preset**: Vite
3. Set **Build Command**: `npm run build`
4. Set **Output Directory**: `dist`
5. Keep `VITE_API_BASE` unset in Vercel so the frontend uses the same-origin `/api` path.
6. The `frontend/vercel.json` rewrite proxies `/api/*` to the Flask service, avoiding browser cross-origin requests. Redeploy and verify `/api/health` after changing the config.

### Backend → Render (Recommended)
1. Connect GitHub repository to Render
2. Create new **Web Service** → **Docker**
3. Set **Dockerfile Path**: `./backend/Dockerfile`
4. Set **Docker Context**: `./backend`
5. Add Environment Variables from `.env.example`:
   - `DB_PATH=/data/windsight.db`
   - `FLASK_DEBUG=false`
   - `CORS_ORIGINS=https://frontend-95b6.vercel.app`
   - (All other vars from `.env.example`)
6. Add **Persistent Disk**:
   - Name: `windsight-data`
   - Mount Path: `/data`
   - Size: 1 GB
7. Set **Health Check Path**: `/api/health`
8. Deploy the service, then verify `/api/health`. This repository uses manual Render service settings and does not include a `render.yaml`.

### Backend → Railway (Alternative)
1. Connect GitHub repository to Railway
2. Create new **Service** → **Dockerfile**
3. Set **Dockerfile Path**: `backend/Dockerfile`
4. Add Environment Variables from `.env.example`
5. Add **Volume**: `windsight-data` → `/data`
6. Set **Health Check Path**: `/api/health`
7. Deploy the service and verify `/api/health`; this repository currently uses manual Railway service settings and does not include a `railway.json`.

### Backend → Fly.io (Alternative)
```bash
# Install flyctl, then:
fly launch --dockerfile backend/Dockerfile --name windsight-backend
fly volumes create windsight_data --region ord --size 1
fly deploy
```

### CORS Configuration
The Vercel frontend uses the same-origin `/api` rewrite, so browser requests pass through Vercel to the backend. Keep backend CORS restricted to explicitly permitted origins if direct cross-origin clients are also needed. The backend's `CORS_ORIGINS` setting is environment-configurable.

### Verification Steps After Deployment
1. Backend health: open `https://oksajn.onrender.com/api/health`
2. Frontend loads: open `https://frontend-95b6.vercel.app`
3. Frontend → Backend: Check browser network tab for successful API calls
4. Import genuine Elexon JSON or CSV exports from the required period. Synthetic fixtures are for automated tests only and must not be presented as real January 2026 results.
5. Verify charts, table, CSV export all work

## 🎥 Video Demo and Submission

The assignment requires one **unlisted YouTube video no longer than 10 minutes**, with two sections:
- **Part 1 — Client pitch (maximum 5 minutes):** business problem, working dashboard, latest eligible forecast information, forecast error metrics, genuine January 2026 findings, and limitations.
- **Part 2 — Technical review (maximum 5 minutes):** architecture, Elexon integration, cutoff logic, data handling, metric calculations, tests, Docker, and deployment.

A ready-to-record script and checklist are provided in [docs/VIDEO_DEMO_SCRIPT.md](docs/VIDEO_DEMO_SCRIPT.md). The script does not count as the video deliverable: record the screen and narration, upload the video as **Unlisted**, and verify it opens in an incognito window before submitting.

**Submission form:** [Full Stack SWE challenge submission v4](https://forms.cloud.microsoft/r/Ljmf1aWESK). Complete the form after the unlisted video, public repository, and live app links have been verified. This README does not claim the form or YouTube upload has been completed.

## 📝 AI Tool Disclosure

ChatGPT was used to help plan the requirements, review implementation details, and identify defects during this assignment. Add any other coding assistants actually used while implementing the project. Do not list tools that were not used.

## ⚠️ Known Limitations

1. **Historical coverage must be verified against returned records**: the dataset API supports queries by published time. The app must still verify real January 2026 delivery coverage and preserve original WINDFOR publishTime values. A latest-only view is not a substitute for all required historical forecast vintages.
2. **Cutoff assumption**: The 11:00 UK D-1 cutoff is configurable for the pilot and must be confirmed against the customer's actual procurement process.
3. **National Only**: No regional/zonal wind breakdown
4. **No Demand Data**: Procurement decisions need demand forecasts (out of scope)
5. **No Balancing Costs**: Imbalance pricing not modeled
6. **SQLite Concurrency**: Not suitable for high-concurrency production use

## 🔮 Future Improvements

- [ ] Verify full WINDFOR vintage coverage using the official history/evolution endpoints and maintain a documented coverage report
- [ ] Multiple cutoff scenarios (gate closure sensitivity analysis)
- [ ] Regional wind forecasts (BNGC, WINDZONE)
- [ ] Demand forecast integration
- [ ] Balancing mechanism cost modeling
- [ ] PostgreSQL for production deployment
- [ ] Authentication & multi-user support
- [ ] Automated scheduled data refresh

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Run `docker compose up --build` and verify
5. Submit a pull request

---

**Built for the UK energy market. Not for operational use without independent validation.**