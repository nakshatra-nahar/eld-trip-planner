# RouteLog backend

A stateless Django 6.1 + Django REST Framework API that geocodes the three trip locations, routes them with Valhalla's truck profile (falling back to OSRM), and runs the pure-Python HOS engine to produce the timeline, stops and FMCSA daily logs. See the [root README](../README.md) for the rules, the algorithm and the API reference.

```bash
uv sync
uv run python manage.py runserver 8000
uv run pytest              # offline suite (recorded Valhalla/OSRM/Photon fixtures, Hypothesis property tests)
uv run pytest -m live      # optional smoke tests against the real Valhalla, OSRM and Photon services
uvx ruff check .
```

## Endpoints

| Method | Path | Returns |
|---|---|---|
| POST | `/api/trips/plan/` | `PlanResponse`: route, timeline, stops, daily logs, summary, assumptions, warnings |
| GET | `/api/geocode/?q=...&limit=6` | US/CA autocomplete results (Photon, falling back to Nominatim; cached in memory) |
| GET | `/api/reverse/?lat=..&lon=..` | Nearest populated place from the offline GeoNames index |
| GET | `/api/health/` | `{"status": "ok"}` |

Errors always use the shape `{"error", "code", "details?"}`. The codes are `validation_error` (400), `geocode_failed` (422), `route_not_found` (422), `rate_limited` (429, with `Retry-After`), `payload_too_large` (413), `upstream_unavailable` (502), `not_found` (404) and `internal_error` (500).

The API is public by design, with no accounts or stored data. Abuse is capped per client IP by `trips/throttling.py`: planning at 20/min (`PLAN_RATE`) and autocomplete at 60/min (`GEOCODE_RATE`). The client is keyed on Vercel's `X-Vercel-Forwarded-For` header.

## Code map

| Path | Role |
|---|---|
| `trips/hos/` | HOS engine with no Django or network imports: `rules.py` (limits), `profile.py` (`LegProfile`), `planner.py` (`plan_events`), `logs.py` (`build_plan`), `audit.py` (independent checker) |
| `trips/planner_service.py` | `plan_trip`: geocode → route → engine → local times → response |
| `trips/services/` | `valhalla.py` (`route_trip`: Valhalla truck routing, splitting legs over the server's 1,500 km limit, OSRM fallback for the whole trip), `routing.py` (OSRM with host failover and a 65 mph truck cap), `geocoding.py`, `places.py` (offline "City, ST" namer and `timezone_at`), `instructions.py` (turn-by-turn text), `geometry.py` (Douglas-Peucker) |
| `trips/data/places.csv.gz` | About 23,000 US/CA populated places with their IANA time zone, rebuilt with `scripts/build_places.py` from GeoNames |
| `scripts/capture_route_fixtures.py` | Re-records the Valhalla/OSRM fixtures replayed by `test_services_valhalla.py` |
| `config/settings.py` | Configured by environment variables; see [`.env.example`](.env.example) |

## Deploying to Vercel

Vercel detects Django from `manage.py` and serves `config/wsgi.py` as one Python function. [`vercel.json`](vercel.json) raises `maxDuration` to 60 s (the planner's upstream budget is 25 s) and pins `trips/data/**` into the bundle. Set `DJANGO_SECRET_KEY` in the project (startup fails without it when DEBUG is off). `DJANGO_DEBUG` defaults to off everywhere except local `manage.py` commands, and `ALLOWED_HOSTS` already includes `.vercel.app`.

```bash
vercel link && vercel env add DJANGO_SECRET_KEY production && vercel --prod
```
