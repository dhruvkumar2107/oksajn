# WindSight Video Demo Script

**Required recording:** one unlisted YouTube video, maximum 10 minutes total. Record Part 1 first and Part 2 second. Keep each part within 5 minutes. The scripts are guides; the video itself must be recorded and uploaded separately.

## Before recording

1. Open the deployed app in an incognito/private window.
2. Test the frontend and `/api/health`.
3. Confirm that January 2026 actuals and forecasts are genuine Elexon data.
4. Fill in the real coverage and metric values below from the running application. Do not guess numbers.
5. If historical vintages or actual values are missing, say so explicitly and demonstrate the warning/import workflow. Do not present empty metrics as forecast performance.
6. Close unrelated tabs, browser notifications, and extension popups. Keep the browser zoom readable.
7. Record both sections in one video and verify it is under 10 minutes.
8. Upload to YouTube as **Unlisted**, then open the share URL in incognito to confirm it is accessible.

---

## Part 1 — Client pitch (target 4:30; maximum 5:00)

### 00:00–00:35 — The business problem

“Hello, and thank you for taking the time to review WindSight. This pilot focuses on one specific procurement question: how much national wind generation could be available for a delivery interval, based on the forecast that was actually available when the day-ahead purchasing decision had to be made?

Wind output changes with weather. A forecast published after the purchasing cutoff cannot fairly be treated as information the buyer had at decision time. WindSight makes that distinction visible and measures forecast error against actual generation.”

### 00:35–01:15 — Scope and data

“This version deliberately uses only the two Elexon datasets specified for the pilot: FUELHH for actual generation, filtered to fuel type WIND, and WINDFOR for forecast generation. The delivery interval is identified by startTime, and each forecast retains its publishTime.

The evaluation period is January 2026. Before reading the metrics, we confirm the data coverage and that the source timestamps support the decision-cutoff analysis. The pilot does not introduce weather providers, demand forecasts, prices, or other generation datasets.”

### 01:15–02:05 — Dashboard overview

“Here is the executive overview. It brings the evaluation period, error metrics, coverage, latest selected forecast publication time, and data quality warnings into one place.

The 11:00 UK time on the day before delivery is a configurable pilot assumption, not a universal claim about every trading desk. It can be changed to match the client's documented decision process. Every selected forecast is checked against that cutoff.”

**On screen:** Point to the evaluation period, latest eligible forecast publication time, matched interval count, coverage, and data quality warnings.

**Replace before recording:** State the real matched interval count and coverage only after confirming the live imported/retrieved dataset. If data is unavailable, demonstrate the honest unavailable-data message instead.

### 02:05–03:00 — Forecast versus actual and error

“The first chart compares actual wind generation with the forecast vintage selected for the decision cutoff. A difference between the lines is the forecast error.

The error convention is forecast minus actual. A positive value means wind generation was overestimated; a negative value means it was underestimated. The error chart uses a zero reference line so the direction of the error is easy to understand.”

**On screen:** Hover a point and show the delivery interval, forecast, actual, and forecast publication timestamp. Use only records from the displayed dataset.

### 03:00–03:55 — Accuracy measures

“WindSight reports four complementary accuracy measures. Mean Absolute Error gives the average size of the error in megawatts. Root Mean Squared Error penalizes larger errors more heavily. Mean bias shows whether forecasts tend to overestimate or underestimate. MAPE expresses error as a percentage, excluding actual values at or below the documented near-zero threshold to avoid misleading divisions.

Coverage is shown with its numerator and denominator. These measures are calculated on intervals with both actual generation and an eligible forecast.”

**On screen:** Point to the cards and their sample counts. Quote real values only if verified.

### 03:55–04:30 — Audit and close

“The interval table makes the result traceable. For each interval it shows actual generation, selected forecast generation, when that forecast was published, the signed error, absolute error, and evaluation status. The records can be filtered and exported to CSV.

This pilot provides a transparent view of wind forecast information and its historical errors. It does not calculate the full optimal purchase quantity, because consumer demand, other generation, interconnector flows, and market costs are intentionally outside the requested data scope. The next step is to confirm the client's precise cutoff and validate complete historical coverage together.”

---

## Part 2 — Technical lead review (target 4:30; maximum 5:00)

### 00:00–00:35 — Architecture

“I’ll now explain how to reproduce and review the implementation. The frontend uses React and Vite. The backend uses Python and Flask. Pandas and NumPy handle normalization and metrics, SQLite stores processed data, Recharts renders the analysis, and Docker Compose runs the frontend and backend together.

The frontend calls Flask through REST endpoints. The deployed Vercel frontend uses a same-origin /api rewrite to reach the backend.”

**On screen:** Show the repository structure and `docker-compose.yml`.

### 00:35–01:20 — Data sources and ingestion

“The Elexon client is in `backend/app/services/elexon_client.py`. It reads the official FUELHH and WINDFOR dataset streams with publication-time filters and bounded time windows. The processing service is `backend/app/services/data_processor.py`.

Actual records are filtered to fuelType WIND. Both datasets are normalized while preserving the delivery startTime. WINDFOR publishTime is retained because it determines whether the forecast was available at decision time. Data is filtered to delivery intervals from 1 January 2026 inclusive to 1 February exclusive.”

### 01:20–02:15 — Forecast selection and metrics

“For every delivery interval, the configured UK-local D-minus-one cutoff is calculated using the Europe/London timezone. The code selects the latest publishTime at or before that cutoff and excludes later forecasts. We use startTime as the primary join key to match actuals and forecasts.

The signed error is forecast minus actual. MAE is the average absolute error, RMSE is the square root of average squared error, bias is the average signed error, and MAPE excludes actual generation at or below the configured threshold. The API returns metrics and sample counts; the frontend does not independently recalculate the authoritative KPIs.”

**On screen:** Show `get_decision_cutoff_for_delivery`, `select_eligible_forecasts`, `evaluate_forecasts`, and metric queries.

### 02:15–03:05 — API and persistence

“The Flask routes are in `backend/app/routes/api.py`. The key endpoints are `/api/health`, `/api/summary`, `/api/forecasts`, `/api/accuracy`, and `/api/intervals`. Refresh and import endpoints expose clear errors when source records are missing or invalid.

SQLite access and schema migration code are in `backend/app/models/__init__.py`. Schema migrations add missing columns without deleting existing rows. The app must never invent production records to make charts look populated.”

### 03:05–03:50 — Tests and Docker

“Automated tests use pytest and mocked HTTP responses. They cover timestamp parsing, WIND filtering, cutoff selection, exclusion of forecasts published after the cutoff, delivery interval matching, error sign, metrics, missing data, and API behavior. GitHub Actions runs backend tests and builds the React frontend.

For a local integrated run, the command is `docker compose up --build`. The frontend is served through Nginx, which proxies /api to Flask. SQLite persists through the configured Docker volume.”

**On screen:** Show the successful CI run and Docker Compose configuration. Only describe tests as passed if the current run actually passed.

### 03:50–04:30 — Deployment, limitations, handover

“The frontend is deployed at https://frontend-95b6.vercel.app and the backend is hosted separately at https://oksajn.onrender.com. The public source is https://github.com/dhruvkumar2107/oksajn.

The main limitation to validate is historical coverage. A valid retrospective evaluation requires genuine January 2026 FUELHH actuals and original WINDFOR forecast publication timestamps. The latest-only forecast view is not enough to reconstruct every vintage. The configured cutoff also needs confirmation with the client. Demand, market prices, other generation, interconnector flows, and balancing economics are outside this narrowly scoped version.

That concludes the implementation walkthrough. The README documents setup, configuration, routes, tests, deployment, and the use of AI tools during development.”
