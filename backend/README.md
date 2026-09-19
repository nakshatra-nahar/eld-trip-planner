# RouteLog backend

A stateless Django 6.1 + Django REST Framework API that geocodes the three trip locations, routes them with OSRM, and runs the pure-Python HOS engine to produce the timeline, stops and FMCSA daily logs. See the [root README](../README.md) for the rules, the algorithm and the API reference.

```bash
uv sync
uv run python manage.py runserver 8000
uv run pytest              # offline suite (recorded OSRM fixtures, Hypothesis property tests)
uv run pytest -m live      # optional smoke test against the real OSRM + Photon services
```

## Endpoints

| Method | Path | Returns |
|---|---|---|
| POST | `/api/trips/plan/` | `PlanResponse`: route, timeline, stops, daily logs, summary, assumptions, warnings |
| GET | `/api/geocode/?q=...&limit=6` | US/CA autocomplete results (Photon, falling back to Nominatim; cached in memory) |
| GET | `/api/reverse/?lat=..&lon=..` | Nearest populated place from the offline GeoNames index |
| GET | `/api/health/` | `{"status": "ok"}` |

Errors always use the shape `{"error", "code", "details?"}`. The codes are `validation_error` (400), `geocode_failed` (422), `route_not_found` (422), `upstream_unavailable` (502), `not_found` (404) and `internal_error` (500).

## Code map

| Path | Role |
|---|---|
| `trips/hos/` | HOS engine with no Django or network imports: `rules.py` (limits), `profile.py` (`LegProfile`), `planner.py` (`plan_events`), `logs.py` (`build_plan`), `audit.py` (independent checker) |
| `trips/planner_service.py` | `plan_trip`: geocode → route → engine → response |
| `trips/services/` | `routing.py` (OSRM with host failover and a 65 mph truck cap), `geocoding.py`, `places.py` (offline "City, ST" namer), `instructions.py` (turn-by-turn text), `geometry.py` (Douglas-Peucker) |
| `trips/data/places.csv.gz` | About 23,000 US/CA populated places, rebuilt with `scripts/build_places.py` from GeoNames |
| `config/settings.py` | Configured by environment variables; see [`.env.example`](.env.example) |

## Deploying to Vercel

Vercel detects Django from `manage.py` and serves `config/wsgi.py` as one Python function. [`vercel.json`](vercel.json) raises `maxDuration` to 60 s (the planner's upstream budget is 25 s) and pins `trips/data/**` into the bundle. Set `DJANGO_SECRET_KEY` in the project (startup fails without it when DEBUG is off). `DJANGO_DEBUG` defaults to off everywhere except local `manage.py` commands, and `ALLOWED_HOSTS` already includes `.vercel.app`.

```bash
vercel link && vercel env add DJANGO_SECRET_KEY production && vercel --prod
```
