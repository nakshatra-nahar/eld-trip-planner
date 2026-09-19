# ELD Trip Planner: Build Spec

A Spotter AI "Full Stack Developer" assessment. The app takes a current location, a pickup location, a dropoff location and "Current Cycle Used (Hrs)". It outputs:
- a map of the route with stops and rests (built on free map APIs);
- route instructions;
- drawn, filled-out FMCSA Driver's Daily Log sheets, one per calendar day.

The grader tests the hosted app for HOS **accuracy**, and **UI/UX quality** weighs heavily ("good design and aesthetics can compensate for some inaccuracies").

The domain reference is `../../INDEX.md`, the verified index of the FMCSA HOS guide, the log-sheet anatomy and the training transcript. The FMCSA guide PDF is at `../../fmcsa-hos-395-drivers-guide-to-hos-2022-04-28-0-1-.pdf`, and the blank log image is `../../blank-paper-log.png`. Paths are relative to this `docs/` folder.

## Stack
- `backend/`: Django 6.1, DRF, django-cors-headers and requests, on Python 3.12, managed by `uv`. Run with `uv run python manage.py runserver 8000` and test with `uv run pytest`. There is no database requirement: the API is stateless. Use SQLite only because Django needs one configured, and have no models.
- `frontend/`: Vite 8, React 19, TypeScript, Tailwind CSS v4 (via `@tailwindcss/vite`), `maplibre-gl` + `react-map-gl` (`react-map-gl/maplibre`), and `lucide-react`. The dev server proxies `/api` to `127.0.0.1:8000`.
- The shared JSON contract is `frontend/src/types/api.ts`. **It is the source of truth.** The backend must emit exactly these snake_case keys and types.
- Deployment target is Vercel: the frontend is a static Vite build, and the backend is a Django WSGI app on the Vercel Python runtime, deployed as a separate project. The frontend reaches the backend through a `/api/*` rewrite. Settings must read `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS` from env, with sensible dev defaults.

## Free external services (no API keys)
- **Routing:** OSRM. Try `https://router.project-osrm.org` first, then fail over to `https://routing.openstreetmap.de/routed-car`. Use `/route/v1/driving/{lon,lat};{lon,lat};{lon,lat}?overview=full&geometries=geojson&steps=true&annotations=distance,duration`. Use a 15 s timeout, 1 retry per host, and a `User-Agent: eld-trip-planner/1.0`.
- **Geocoding and autocomplete:** Photon (`https://photon.komoot.io/api/?q=...&limit=6&bbox=-170,15,-50,72`), restricted to US/CA results. Fall back to Nominatim (`https://nominatim.openstreetmap.org/search?format=jsonv2&countrycodes=us,ca&addressdetails=1`) with a proper User-Agent.
- **Remark place names** ("City, ST") come from an **offline** nearest-place dataset. Build it from GeoNames `cities500.zip` (or `cities1000.zip`) filtered to US + CA, with US state and Canadian province abbreviations, and save it gzipped at `backend/trips/data/places.csv.gz` (name, admin abbrev, lat, lon, population). Commit the build script to `backend/scripts/build_places.py`. Look places up with a simple lat/lon grid-bucket index. Avoid reverse-geocoding APIs for this: they are rate-limited.
- **Map tiles:** OpenFreeMap (`https://tiles.openfreemap.org/styles/positron` or `liberty`) with MapLibre. Always show the attribution.

## HOS engine (pure Python, `backend/trips/hos/`, no Django or network imports)

### Rules
These are for a property-carrying driver on the 70-hour/8-day cycle, with no adverse driving conditions. Constants live in `rules.py`:

| Constant | Value | Source |
|---|---|---|
| MAX_DRIVING | 11 h driving per duty period | FMCSA p.6 |
| DUTY_WINDOW | 14 consecutive hours from the start of the duty period; no driving after it | FMCSA p.6 |
| BREAK_AFTER_DRIVING | 8 h cumulative driving; then a ≥30-consecutive-minute non-driving interruption is required | FMCSA p.10 |
| BREAK_MINUTES | 30; status OFF | FMCSA p.10 |
| RESET_OFF | 600 min (10 h) consecutive; status `rest_status` (default SB) | FMCSA p.6-7 |
| CYCLE_LIMIT | 70 h on-duty (D+ON) in 8 days; no driving at or above it | FMCSA p.10-11 |
| RESTART | 34 h; status OFF; resets the cycle to 0 and also counts as a 10-h reset | FMCSA p.11 |
| FUEL_INTERVAL | 1,000 miles; fuel stop is `fuel_stop_minutes` (default 30) ON | brief |
| PICKUP / DROPOFF | 60 min each; status ON | brief |
| PRE_TRIP | 30 min ON at the start of every duty period, if `include_inspections` | training video |
| POST_TRIP | 15 min ON before each 10-h rest or 34-h restart that ends a duty period, and after dropoff, if `include_inspections` | FMCSA p.5 (inspection = on duty) |
| TRUCK_SPEED_CAP_MPH | 65; each OSRM annotation segment takes `max(osrm_seconds, distance / 65 mph)` | assumption |

### Assumptions (also returned in `assumptions[]`)
- The driver starts the trip rested: ≥10 h off, so the 11-h and 14-h clocks are fresh and there is 0 driving since the last break.
- The driver is off duty from local midnight until the start time on day 1, and off duty after the trip ends until midnight.
- The tank is full at the current location.
- "Current Cycle Used" hours do not roll off during the trip. This is **conservative**, because no per-day history is given.
- All times use the home-terminal time of the start location. There is no time-zone conversion.
- A single driver: no split sleeper-berth and no team driving.

### Algorithm
Everything is simulated in **integer minutes** from the trip start, so each log sheet sums to exactly 1,440 minutes. Round each driving chunk to whole minutes, and cover distance proportionally inside the profile.

State: `t`, `window_start` (None if no duty period is active), `drive_in_period`, `drive_since_break`, `nondriving_run`, `cycle_used` (starts at cycle_used_hours×60), `miles_since_fuel`, `leg_index`, `leg_progress_minutes`.

Activities in order: drive leg 0 (current→pickup; skip if under 0.1 mi), PICKUP, drive leg 1 (pickup→dropoff), DROPOFF, then POST_TRIP.

Before any on-duty activity (drive, pickup, dropoff, fuel) when `window_start is None`, **start a duty period**. First, if `cycle_used` > CYCLE_LIMIT − 60 min and driving remains, take a RESTART. Then set `window_start = t` and do PRE_TRIP if enabled.

Driving loop, evaluated in priority order at the top of each iteration:
1. If `cycle_used >= CYCLE_LIMIT`: take POST_TRIP (if enabled and a period is active), then RESTART (34 h OFF). Reset everything, including `cycle_used = 0`.
2. Else if `drive_in_period >= 11 h` or `t - window_start >= 14 h`: take POST_TRIP (if enabled), then REST (10 h, `rest_status`). Reset the period.
3. Else if `drive_since_break >= 8 h`: take BREAK (30 min OFF).
4. Else if `miles_since_fuel >= 1000` (with a small epsilon): FUEL.
5. Else drive a chunk of `min(11h − drive_in_period, 14h − (t − window_start), 8h − drive_since_break, 70h − cycle_used, minutes until miles_since_fuel hits 1000, minutes to leg end)`, with a minimum of 1 minute. The last chunk of a leg may be partial: round its seconds to the nearest minute, with a minimum of 1 minute if distance is over 0.

Non-driving bookkeeping: any consecutive non-driving time (any status) accumulates in `nondriving_run`. Once it reaches 30 min, set `drive_since_break = 0`. Driving resets `nondriving_run = 0`. So a 30-min pre-trip, a 1-h pickup or dropoff, a 30-min fuel stop, a break, a rest and a restart all satisfy the 30-min break requirement.

A REST or RESTART resets `drive_in_period`, `drive_since_break` and `window_start = None`. On-duty time (D and ON) adds to `cycle_used`. Pickup, dropoff and post-trip are allowed even if the cycle or window is exhausted, because on-duty not-driving is legal. Only driving is blocked.

Every event records:
- kind and status;
- start and end minutes;
- start_mile and end_mile (cumulative trip miles);
- leg_index;
- start and end coordinates, interpolated from the leg profile.

### Leg profile (`profile.py`)
Built from the OSRM leg annotation arrays:
- `coords` (lon, lat);
- `cum_miles`;
- `cum_minutes` (truck-adjusted).

Interpolation helpers:
- `minute_to_mile`;
- `mile_to_minute`;
- `coord_at_mile`.

The `step_at_mile` helper returns the OSRM step's road name/ref so remarks can say "I 80 near Joliet, IL".

### Daily logs (`logs.py`)
1. Convert the events to absolute datetimes from `start_time`.
2. Prepend OFF from 00:00 on the start date, and append OFF until 24:00 on the end date.
3. Split events at midnights.
4. Build each sheet:
   - **segments:** merge consecutive same-status pieces, covering 0-1440;
   - **totals:** hours, summing to 24;
   - **total_miles:** driving miles that fall on that date, splitting a driving event across midnight by its profile;
   - **remarks:** one per non-driving event piece on that sheet (not the padding OFF). Give its start/end minute on the sheet, the location name ("City, ST") and a note. A piece continued from the previous day gets a note ending "(cont.)";
   - **on_duty_hours:** D + ON;
   - **cycle_hours_used:** at the end of the day (initial + trip on-duty; 0 after a restart, then accumulating);
   - **cycle_hours_available:** 70 − used, floored at 0;
   - **from_location / to_location.**
5. Name locations with an injected `place_namer(lat, lon, road=None) -> str`, so the engine stays pure.

### Tests (pytest + hypothesis)
Invariants to check for many random trips (random leg lengths 0-3,500 mi, random speeds, cycle 0-70, random start times, both option settings):
- no driving after 11 h in a period;
- no driving after 14 h from the window start;
- ≤ 8 h driving without a ≥30-min non-driving run;
- no driving while cycle_used ≥ 70 h (with no roll-off);
- ≤ 1,000 mi between fuel stops;
- pickup and dropoff are each exactly 60 min ON;
- events are contiguous and non-overlapping;
- total driven miles equal the route miles;
- every log sheet's segments cover 0-1440 contiguously, and totals sum to 24.00;
- per-day miles sum to the route miles.

Also write hand-calculated scenario tests:
- a short trip that finishes the same day;
- exactly 11 h of driving;
- a trip that needs a 34-h restart (cycle used 65);
- cycle used 70 at the start;
- current == pickup;
- a 2,500-mile multi-day trip.

## Backend API (`backend/trips/`)
- `POST /api/trips/plan/`: body is `PlanRequest`, response is `PlanResponse`.
  - **Validation:** cycle 0-70; start_time format; each location has lat/lon or a non-empty query. Invalid input returns 400 `ApiError` (`validation_error`).
  - **Geocoding:** geocode any `query` locations.
  - **Routing:** call OSRM once with 3 waypoints (2 legs). Unroutable input returns 422 `route_not_found`; all hosts failing returns 502 `upstream_unavailable`.
  - Then build the profiles and run the engine.
  - Name every event and stop location with the offline dataset (plus the OSRM road ref when the stop is on a highway).
  - Simplify the display geometry (Douglas-Peucker to about 1,500 points total). Leg geometries are simplified too.
  - Build text instructions from the OSRM steps. Write your own English generator in `services/instructions.py` covering depart, arrive, turn, new name, continue, merge, on ramp, off ramp, fork, end of road, roundabout/rotary (with exit number), use lane, notification, and the modifiers. Collapse consecutive trivial steps.
- `GET /api/geocode/?q=...`: returns `GeocodeResponse`. Require at least 2 characters, and cache results in memory. Used by the autocomplete.
- `GET /api/reverse/?lat=..&lon=..`: returns `ReverseGeocodeResponse` from the offline dataset, for "Use my location".
- `GET /api/health/`: returns `{"status":"ok"}`.
- Pass the view's total time budget to the engine and services. Aim for under 8 s for a 3,000-mile trip on a warm function.

## Frontend design
**The audience:** trucking-industry reviewers at Spotter AI, who know ELDs well. The UI must feel like a polished, modern logistics product (think Samsara/Motive dashboards), not a tutorial app.
- **Aesthetic:** clean and confident. Light theme with an ink/navy base and a single warm amber/orange "highway" accent, plus status colors per duty line:
  - OFF: slate
  - SB: indigo
  - D: emerald/green
  - ON: amber

  Use these consistently across the map markers, itinerary, charts and log legend.
- **Type:** Inter (or Geist) from Google Fonts, with tabular numbers, and a mono font for the log values.
- **Layout (desktop):** a sticky top bar with the product name ("RouteLog" or "HOS Trip Planner"), and a subtle "FMCSA 70h/8-day · Property-carrying" badge. The main area is a two-column split:
  - **Left:** a ~440 px planner panel with the trip form, and the trip summary after planning.
  - **Right:** a large map card.

  Below both is a full-width results area with tabs: **Itinerary**, **Daily Logs** (sheet count badge) and **Directions**. On mobile, stack everything with the map above the results.
- **Form:**
  - three location autocompletes, each with an icon, keyboard navigation and debounce, "Use my location" on Current, and a swap-pickup/dropoff button;
  - Current Cycle Used as a number input plus a 0-70 slider, with a helper line showing the hours left;
  - a trip start date-time, defaulting to the next full hour;
  - collapsible "Advanced": inspections toggle, 10-h rest status (Sleeper berth / Off duty), fuel stop minutes;
  - collapsible "Log sheet details" (driver, co-driver, carrier, main office, home terminal, truck #, trailer #, shipping doc), persisted in `localStorage`;
  - "Try an example" chips that fill realistic trips (short, cross-country, and near the cycle limit);
  - a primary "Plan trip" button with a loading state.
- **Map:**
  - the route line with leg 0 and leg 1 visually distinct;
  - start (current), pickup and dropoff pins;
  - stop markers by kind (fuel, break, rest, restart, pre/post-trip), with lucide icons in colored circles;
  - hover/click popups showing the time window, duration, location and mile marker;
  - a legend, and fit-to-route;
  - selecting an itinerary item flies to its stop.
- **Summary:**
  - stat tiles: total miles, driving hours, trip duration (d h m), log sheets, fuel stops, rests/restarts, and cycle hours left at arrival;
  - a compact horizontal "duty timeline bar" for the whole trip, colored by status and scaled by time;
  - warnings (e.g. a 34-h restart was required).
- **Itinerary:** a vertical timeline grouped by day (Day N · date). Each row shows:
  - the time range and duration;
  - a status chip;
  - the activity label and location;
  - miles for driving rows.
- **Daily Logs:** FMCSA-style SVG sheets (see below), with a day switcher (pills) and "Show all". The toolbar has Print / Save as PDF (print CSS, one sheet per landscape page) and download of the current sheet as SVG or PNG.
- **Directions:** per-leg collapsible lists with maneuver icons, text and distance, plus a leg header with distance and time.
- **Quality bar:**
  - an empty state that explains the app;
  - skeletons while loading;
  - friendly error messages;
  - no layout shift;
  - accessible labels and focus rings;
  - 44 px touch targets;
  - no console errors;
  - `npm run build` passes with zero TS errors.

## Log sheet SVG (`frontend/src/components/logsheet/`)
Model the sheet on `blank-paper-log.png` and the FMCSA form (PDF p.15/19). Use a landscape viewBox of about 1100×850, render crisp at any width, and make it print-ready.

- **Title block:**
  - "DRIVER'S DAILY LOG" / "(ONE CALENDAR DAY — 24 HOURS)" and "U.S. DEPARTMENT OF TRANSPORTATION";
  - the ORIGINAL/DUPLICATE retention notes;
  - the date (month/day/year) and a sheet "Day N of M";
  - From/To;
  - Total Miles Driving Today;
  - Total Mileage Today (same value; single driver);
  - Truck/Tractor & Trailer numbers;
  - Name of Carrier, Main Office Address and Home Terminal Address;
  - Driver signature (driver name in a script-like font, or italic mono);
  - Co-driver (default "N/A").
- **Grid:** a black header bar with "Mid-night, 1…11, Noon, 1…11, Mid-night", 24 hour columns and 4 rows labeled "1. Off Duty", "2. Sleeper Berth", "3. Driving" and "4. On Duty (not driving)".
  - Each hour has 15-min ticks (short) and a 30-min tick (longer), as in the blank form.
  - A "Total Hours" column on the right shows each row's hours (e.g. `10.25` or `10:15`) and a double-underlined grand total `24`.
- **Duty line:** a continuous "pen" path (dark blue ink, about 2.5 px) through the middle of the active row for each segment, with vertical connectors at every status change.
- **Remarks:** a second hour ruler under the grid, labeled "REMARKS".
  - For each remark, draw a bracket (a cup shape) under its start-end span, and the "City, ST — note" text rotated about −45° from the start point, as in the FMCSA completed log.
  - Stagger labels to avoid overlap when remarks are close together.
- **Shipping documents:** "DVL or Manifest No." and "Shipper & Commodity" lines, filled from the header details.
- **Recap (70 Hour / 8 Day):**
  - on duty today (lines 3 & 4);
  - A: cycle hours used, including today;
  - B: hours available tomorrow (70 − A);
  - the footnote "*34 consecutive hours off duty resets to 70 available". Show "34-hr restart taken" if one occurred that day.
- **Visual:** paper-white background with a subtle border, form lines in near-black, and filled-in values in blue "ink" (mono or handwriting-ish font).

## File ownership (parallel build, do not edit others' files)
- **A. HOS engine:** `backend/trips/hos/**` and `backend/trips/tests/test_hos_*.py`.
- **B. Backend services and API:**
  - `backend/config/**`, `backend/trips/{services/**, data/**, views.py, urls.py, serializers.py, planner_service.py, apps.py, __init__.py}`;
  - `backend/scripts/**`, `backend/trips/tests/test_api*.py` and `backend/trips/tests/test_services*.py`;
  - `backend/pyproject.toml` (the only role allowed to `uv add`) and `backend/conftest.py` / `pytest.ini`.
- **C. Frontend app:** all of `frontend/**` except `frontend/src/components/logsheet/**` and `frontend/src/types/api.ts`. The only role allowed to `npm install`.
- **D. Log sheet:** `frontend/src/components/logsheet/**` only. It exports `DailyLogsView` with props `{ logs: DailyLog[]; header: LogHeaderDetails; tripLabel?: string }`. Adds no new npm dependencies.

## Engine public interface (contract between A and B)

```python
# backend/trips/hos/profile.py
@dataclass(frozen=True)
class RouteStep:            # one OSRM step within a leg, leg-relative miles
    start_mile: float
    end_mile: float
    road: str               # step "ref" if present (e.g. "I 80"), else "name", else ""

class LegProfile:
    def __init__(self, coords: list[tuple[float, float]],   # (lon, lat), len N >= 2
                 seg_miles: list[float],                   # len N-1
                 seg_minutes: list[float],                 # len N-1, ALREADY truck-adjusted
                 steps: list[RouteStep] | None = None): ...
    total_miles: float
    total_minutes: float
    def mile_at_minute(self, minute: float) -> float: ...
    def minute_at_mile(self, mile: float) -> float: ...
    def coord_at_mile(self, mile: float) -> tuple[float, float]: ...   # (lon, lat)
    def road_at_mile(self, mile: float) -> str: ...                    # "" if unknown
    @classmethod
    def straight(cls, start: tuple[float, float], end: tuple[float, float],
                 miles: float, minutes: float, n: int = 50) -> "LegProfile": ...  # for tests / zero-length legs

# backend/trips/hos/__init__.py re-exports:
@dataclass
class PlanOptions:
    include_inspections: bool = True
    rest_status: str = "SB"          # "SB" | "OFF"
    fuel_stop_minutes: int = 30

PlaceNamer = Callable[[float, float, str | None], str]   # (lat, lon, road) -> "City, ST" / "I 80 near City, ST"

def build_plan(legs: list[LegProfile],           # exactly 2 legs: current->pickup, pickup->dropoff
               start_time: datetime,             # naive local home-terminal time
               cycle_used_hours: float,
               options: PlanOptions,
               place_namer: PlaceNamer) -> dict:
    """Returns a dict with keys: timeline, stops, daily_logs, summary, assumptions, warnings.
    Values are JSON-ready and match frontend/src/types/api.ts (TimelineEvent[], Stop[], DailyLog[],
    TripSummary, string[], string[]). Numbers rounded: hours to 2 dp, miles to 1 dp."""

def plan_events(legs, cycle_used_hours, options) -> list[DutyEvent]   # lower-level, used by tests
```
Service B builds the `LegProfile`s from OSRM (`legs[i].annotation.distance/duration`, geometry coordinates, steps) and applies the 65 mph truck cap when it builds `seg_minutes`. It calls `build_plan` and adds `input` and `route` to form the `PlanResponse`. The warnings from `build_plan` include things like "34-hour restart required: cycle hours exhausted on day N". B may add routing warnings.
