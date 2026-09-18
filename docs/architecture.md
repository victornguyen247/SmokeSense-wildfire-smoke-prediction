# System Architecture Overview

This document explains how SmokeSense fits together and what that means for day-to-day development. Read it before working in a part of the system you haven't touched before — most avoidable bugs in a project like this come from code crossing a boundary it shouldn't.

---

## 1. What the system does

SmokeSense answers one question quickly: **"Is wildfire smoke likely to affect this location soon?"**

To do that, it continuously ingests wildfire detections, weather, and air-quality data; turns that raw data into features; runs a machine-learning model to forecast PM2.5 for the next 1–24 hours; and serves those forecasts through an API to an interactive map. A secondary **City Air Quality History** view reuses the same stored historical data to show a city's multi-year PM2.5 trend.

---

## 2. The big picture

```
   External data sources
   (FIRMS, NWS, AirNow, PurpleAir)
              │
              ▼
   ┌─────────────────────┐   scheduled pulls
   │   Ingestion worker  │◄─────────────────── Celery + Redis
   │  (connectors +      │
   │   normalize)        │
   └─────────┬───────────┘
             │ raw + cleaned records
             ▼
   ┌─────────────────────┐
   │  PostgreSQL + PostGIS│  ◄── single source of truth
   │  (fire, weather,     │      (historical + live)
   │   pm25, predictions) │
   └─────────┬───────────┘
             │
      ┌──────┴────────┐
      ▼               ▼
 ┌─────────┐    ┌──────────────┐
 │ features│    │   ml/        │  training (offline)
 │ (spatial│───▶│  models +    │─────► model artifact
 │  + time)│    │  inference   │
 └─────────┘    └──────┬───────┘
                       │ predict()
                       ▼
              ┌──────────────────┐
              │  FastAPI backend │  HTTP/JSON
              │  (routes →       │◄──────────────┐
              │   services)      │               │
              └──────────────────┘               │
                       │ /api/...                │
                       ▼                         │
              ┌──────────────────┐               │
              │  React + Vite    │───────────────┘
              │  dashboard + map │
              └──────────────────┘
```

The key idea: **data flows one way** — from external sources, through ingestion, into the database, through features and the model, out through the API, to the frontend. Each stage depends only on the stage before it.

---

## 3. The components

### Ingestion (`backend/ingestion/`)
A scheduled Celery worker pulls new fire, weather, and air-quality data at appropriate intervals, normalizes all timestamps to **UTC**, validates fields, and writes both raw and cleaned records to the database. It keeps source timestamps and identifiers so we can audit exactly what data was available at prediction time.

### Database (`PostgreSQL + PostGIS`)
The single source of truth. Holds raw and cleaned observations, engineered data, and model predictions. PostGIS gives us spatial types and queries (distance from fire to location, points within a region). The same historical PM2.5 store backs both model training and the City Air Quality History view — no separate pipeline.

### Features (`backend/features/`)
Turns raw records into model inputs: distance and bearing from fire to location, wind alignment, wind/humidity/temperature, lagged PM2.5, time-of-day, and so on. Shared by training and live inference so the same feature means the same thing in both.

### ML (`backend/ml/`)
Training, evaluation, and inference. Training runs **offline** and produces a model artifact. Inference loads that artifact and exposes a `predict()` function. See [ml.md](ml.md).

### Backend API (`backend/app/`)
A FastAPI application. Routes are thin: validate the request, call a service, return the response. Services hold the business logic and call into `ml/inference` for predictions and into the database for data. See [backend.md](backend.md).

### Frontend (`frontend/`)
A React + Vite app: the interactive map, forecast cards, the "why?" explanation panel, alerts, historical playback, and the City Air Quality History screen. It talks to the backend only through the services layer. See [frontend.md](frontend.md).

---

## 4. What this means for development

When you add a feature, think about **which stage of the flow it belongs to**, and keep it there.

**Respect the one-way dependency.** The dependency direction is:

```
frontend → api → services → ml/inference → features → database
```

Code may depend on things **to its right**, never to its left. In particular:

- `app/services/` may import from `ml/inference/`. **`ml/` must never import from `app/`.** Training and inference code must not know that a web request exists. This is the single most important rule in the codebase — it's what lets the model be trained, tested, and run without the web server, and keeps the API container from having to load the whole training stack.
- Routes call services. Services are not called by `ml/`. The frontend never reaches past the API.

**Put code in the right layer.**

- A **route** validates input and returns output. If it contains an `if` that decides *business* behavior, that belongs in a service.
- A **service** holds business logic and orchestrates: fetch data, call the model, shape the result.
- **Feature logic** (how we compute wind alignment, how we lag PM2.5) lives in `features/`, so training and inference stay identical. Don't recompute a feature inline in a service.

**One source of truth for AQI thresholds.** The PM2.5/AQI breakpoints that decide "unhealthy" live in `backend/shared/aqi.py`. The model's threshold-exceedance labels and the frontend's risk coloring must both derive from the same definition. If these drift, the map will say "unhealthy" where the model didn't, and every evaluation number becomes suspect.

**Everything is time-aware.** This system is about *when* data was available. Always store UTC. Never let future information leak into a prediction or a training split (see [ml.md](ml.md) for why this is critical).

**Ask before crossing a boundary.** If a change seems to need the frontend to do something the backend should, or the ML code to know about an HTTP request, stop and raise it. That need is usually a sign the code is in the wrong layer.

---

## 5. Why this shape

A capstone with six people and three months fails most often from **coupling**, not from missing features. When training code depends on the web app, one person can't work without breaking another's. When the frontend computes its own risk thresholds, the map and the model silently disagree. The boundaries above exist so that six people can work in parallel and the pieces still fit — and so that when something breaks, the failure is contained to one stage of the flow instead of rippling across all of them.
