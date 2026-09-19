# ELD Trip Planner: Design Notes

RouteLog plans a property-carrying truck trip under the FMCSA hours-of-service rules. It takes a current location, a pickup location, a drop-off location and "Current Cycle Used (Hrs)", and outputs:
- a map of the route with stops and rests (built on free map APIs);
- route instructions;
- drawn, filled-out FMCSA Driver's Daily Log sheets, one per calendar day.

These notes record how the app is built and why; the root README has the overview. The domain references are the FMCSA *Interstate Truck Driver's Guide to Hours of Service* (April 2022; page numbers below cite it), the blank paper daily-log form, and a carrier training video on filling out a paper log.

## Stack
- `backend/`: Django 6.1, DRF, django-cors-headers and requests, on Python 3.12, managed by `uv`. It runs with `uv run python manage.py runserver 8000` and is tested with `uv run pytest`. The API is stateless: SQLite is configured only because Django expects a database, and there are no models.
- `frontend/`: Vite 8, React 19, TypeScript, Tailwind CSS v4 (via `@tailwindcss/vite`), `maplibre-gl` + `react-map-gl` (`react-map-gl/maplibre`), and `lucide-react`. The dev server proxies `/api` to `127.0.0.1:8000`.
- The shared JSON contract is `frontend/src/types/api.ts`. **It is the source of truth.** The backend emits exactly these snake_case keys and types, and a contract test checks it.
- Deployment target is Vercel: the frontend is a static Vite build, and the backend is a Django WSGI app on the Vercel Python runtime, deployed as a separate project. The frontend reaches the backend through a `/api/*` rewrite. Settings read `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS` from env. `DJANGO_DEBUG` defaults to off (only local `manage.py` commands turn it on), and startup fails without `DJANGO_SECRET_KEY` when it is off.

## Free external services (no API keys)
- **Routing:** Valhalla `truck` costing on the FOSSGIS public server (`https://valhalla1.openstreetmap.de/route`), in `services/valhalla.py` (`route_trip` is the single routing entry point). Requests use `costing=truck`, `units=miles` and English directions. Calls run one at a time across the process, at least 0.25 s apart, each with a 12 s timeout; all Valhalla calls of one trip get at most 15 s, and 8 s of the request budget is always kept for the fallback. The server rejects a request whose locations are more than 1,500 km apart in a straight line (summed over the request), so a leg over 1,450 km is split into road chunks under 1,200 km. The split points sit on interstate (`I `) steps of the OSRM route of the same trip and are sent as `break_through` locations with the OSRM heading; short hops are packed into as few requests as the limit allows, and the chunks are stitched back into one leg. Road labels drop the direction ("I 65 South" becomes "I 65"). Any Valhalla failure (network error, timeout, HTTP error, error answer, bad data) falls back to OSRM for the whole trip: `route.truck_routing` is then false and the warnings open with "Truck routing was unavailable, so this route follows the car road network (OSRM) with a 65 mph cap; check it for truck restrictions." When a truck leg is far longer than the straight line, it is compared with the OSRM route; if the truck route is longer by both 1.35× and 50 mi (for example Vancouver → Seattle, where OpenStreetMap marks the Blaine crossing truck-restricted), the OSRM car route is used, `detour_miles` is set and the warnings say so.
- **Routing fallback and split points:** OSRM, in `services/routing.py`. It tries `https://router.project-osrm.org` first, then fails over to `https://routing.openstreetmap.de/routed-car`, calling `/route/v1/driving/{lon,lat};{lon,lat};{lon,lat}?overview=full&geometries=geojson&steps=true&annotations=distance,duration`. Timeouts are 3 s to connect and 15 s to read (the first host's read timeout is capped at half the remaining budget, so a hung host cannot starve the mirror). A host is retried once after a connection error, 5xx or 429; after a timeout the next host is tried straight away. Every upstream call sends `User-Agent: eld-trip-planner/1.0 (+<UPSTREAM_CONTACT>; ...)`.
- **Geocoding and autocomplete:** Photon (`https://photon.komoot.io/api/?q=...&limit=6&bbox=-170,15,-50,72`), restricted to US/CA results. For a city-style query (no digits), settlements rank first, then those in a state named in the query ("Dallas, GA"), then by population from the offline dataset ("Chic" offers Chicago before Chico). Nominatim (`https://nominatim.openstreetmap.org/search?format=jsonv2&countrycodes=us,ca&addressdetails=1`) is the fallback for the plan's one-shot lookups only, because Nominatim's usage policy forbids autocomplete. An empty answer is cached only when every provider answered.
- **Remark place names** ("City, ST") and **time zones** come from an **offline** nearest-place dataset. `backend/scripts/build_places.py` builds it from GeoNames `cities500.zip` (or `cities1000.zip`) filtered to US + CA, with US state and Canadian province abbreviations, and saves it gzipped at `backend/trips/data/places.csv.gz` (name, admin abbrev, lat, lon, population, IANA `tz`). `timezone_at(lat, lon)` returns the nearest place's zone ("UTC" when nothing is in range); `tzdata` is a dependency so the zones resolve on Vercel. Lookups use a 1° lat/lon grid-bucket index, so no rate-limited reverse-geocoding API is called.
- **Map tiles:** OpenFreeMap (`https://tiles.openfreemap.org/styles/positron` or `liberty`) with MapLibre. The attribution is always shown.

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
| RESTART | 34 h; status OFF; resets the cycle to 0 and also counts as a 10-h reset. A restart that opens the trip counts the off-duty time since midnight (`prior_off_duty_minutes`), so it lasts 34 h minus that (26 h for an 08:00 start) | FMCSA p.11 |
| FUEL_INTERVAL | 1,000 miles; fuel stop is `fuel_stop_minutes` (default 30) ON | brief |
| PICKUP / DROPOFF | 60 min each; status ON | brief |
| PRE_TRIP | 30 min ON at the start of every duty period, if `include_inspections` | training video |
| POST_TRIP | 15 min ON before each 10-h rest or 34-h restart that ends a duty period, and after dropoff, if `include_inspections` | FMCSA p.5 (inspection = on duty) |
| TRUCK_SPEED_CAP_MPH | 65; each route segment takes `max(router_seconds, distance / 65 mph)` (Valhalla's truck speeds are usually below it) | assumption |
| MIN_USEFUL_DRIVING | 60 min; see the restart decision below | planner heuristic |
| MIN_DRIVE_AFTER_STOP | 15 min; a break or fuel stop that would be followed by less driving ends the duty period instead | planner heuristic |
| FUEL_EARLY_MILES | 75 mi; fuel falling due within this distance is taken at a stop that happens anyway (rest, 8-h break, pickup) | planner heuristic |
| FUEL_BEFORE_REST_DRIVING | 3 h (11 h − 8 h); fuel that would fall due within this much of the next duty period's driving is taken before the rest or restart (the whole period when fuel stops are under 30 min), if that adds no fuel stop to the trip | planner heuristic |
| BREAK_EARLY_MINUTES | 60; a fuel stop under 30 min is followed by the 30-min break at the same place when the break would fall due within this much driving | planner heuristic |

### Assumptions (also returned in `assumptions[]`)
- The driver starts the trip rested: ≥10 h off, so the 11-h and 14-h clocks are fresh and there is 0 driving since the last break.
- The driver is off duty from local midnight until the start time on day 1, and off duty after the trip ends until midnight.
- The tank is full at the current location.
- "Current Cycle Used" hours do not roll off during the trip. This is **conservative**, because no per-day history is given.
- Log sheets use the home-terminal time zone of the start location for the whole trip, even across time zones (FMCSA p.16). The API adds each stop's local time.
- A 34-hour restart is taken when the rest of the trip's driving no longer fits in the 70-hour cycle, at the trip start or in place of the 10-hour rest that gives the earliest arrival. A restart at the trip start counts the off-duty time since midnight.
- A single driver: no split sleeper-berth and no team driving.

### Algorithm
Everything is simulated in **integer minutes** from the trip start, so each log sheet sums to exactly 1,440 minutes. Each driving chunk is rounded to whole minutes, and distance is covered proportionally inside the profile.

State (`_Planner` in `planner.py`): `t`, `window_start` (None if no duty period is active), `drive_in_period`, `drive_since_break`, `nondriving_run`, `cycle` (on-duty minutes in the cycle; starts at cycle_used_hours×60), `miles_since_fuel`, and the position: `pos_leg` (the leg being driven) and `progress` (whole minutes of driving into it).

Activities in order: drive leg 0 (current→pickup; skip if under 0.1 mi), PICKUP (preceded by FUEL when fuel is due within FUEL_EARLY_MILES), drive leg 1 (pickup→dropoff), DROPOFF, then POST_TRIP.

Before any on-duty activity (drive, pickup, dropoff, fuel) when `window_start is None`, the planner **starts a duty period**: a RESTART first if one is needed (below), then `window_start = t` and the PRE_TRIP if enabled. If fuel was due before the rest but there was no cycle room to take it, the driver fuels right after the pre-trip, before driving off.

**Restart decision** (made when a duty period ends, counting its post-trip, and again when one opens, with the same answer, so a 10-h REST is never immediately followed by a RESTART). Only driving must end within 70 h: the drop-off and final post-trip after the last driving minute are on-duty not driving, which FMCSA allows past 70 h (p.10). So:
- no restart if no driving remains, or if the rest of the trip's on-duty work up to its last driving minute fits in the cycle (remaining driving, plus a pre-trip per remaining period and post-trips between them, the pickup if driving follows it, and the fuel stops still needed);
- otherwise restart when the next period could not drive `min(remaining driving, MIN_USEFUL_DRIVING)` after its unavoidable on-duty work (pre-trip, the pickup if parked there, a fuel stop if due, and the post-trip reserved for before the restart).

**Restart placement (search).** That rule alone restarts as late as possible, which often costs an extra 10-h rest just before the restart. So an *optional* restart is offered at every point where the rest of the trip does not fit in the cycle hours left but would fit in a fresh 70 h: each point where a 10-h rest is due, plus the trip start. `plan_drives` plans the trip greedily, then once more for each offered point with the restart taken there, and keeps the earliest arrival (the greedy plan on a tie). When the remaining work is more than a fresh cycle, nothing is offered and the greedy plan stands. For LA → Phoenix → NYC at 30 h used this replaces the first 10-h rest with the restart and arrives about 11 h earlier than rest-then-restart.

Driving loop, evaluated in priority order at the top of each iteration:
1. If the cycle room is under 1 min: POST_TRIP (if enabled and a period is active), then RESTART (34 h OFF), which resets everything, including `cycle = 0`. The cycle room is `70 h − cycle`, minus the 15-min post-trip whenever the rest of the trip does not fit in the cycle, so the post-trip before a restart still ends by 70 h and no mid-trip recap exceeds 70 h.
2. Else if `drive_in_period >= 11 h` or `t - window_start >= 14 h`: if fuel is due within FUEL_EARLY_MILES, or within FUEL_BEFORE_REST_DRIVING of the next period's driving (and fueling now adds no fuel stop), FUEL first; then POST_TRIP (if enabled), then REST (10 h, `rest_status`), or RESTART per the restart decision and search. The period resets.
3. Else if `drive_since_break >= 8 h`: if fuel is due (or due within FUEL_EARLY_MILES) and `fuel_stop_minutes >= 30`, FUEL instead (it satisfies the break). Else if less than MIN_DRIVE_AFTER_STOP of driving could follow the break (11-h, 14-h or cycle limit) and the leg does not end within that, the duty period ends as in step 2. Else BREAK (30 min OFF).
4. Else if `miles_since_fuel >= 1000` (with a small epsilon): FUEL; but if less than MIN_DRIVE_AFTER_STOP of driving could follow it (14-h window or cycle), the duty period ends as in step 2 (fuel, post-trip and rest at one stop). A fuel stop shorter than 30 min is followed by the BREAK at the same place when the break would fall due within BREAK_EARLY_MINUTES. A fuel stop (or the pickup) that would leave no cycle room to drive on is preceded by the restart instead.
5. Else drive a chunk of `min(11h − drive_in_period, 14h − (t − window_start), 8h − drive_since_break, 70h − cycle, minutes until miles_since_fuel hits 1000, minutes to leg end)`, with a minimum of 1 minute. The last chunk of a leg may be partial: its seconds are rounded to the nearest minute, with a minimum of 1 minute if distance is over 0.

Non-driving bookkeeping: any consecutive non-driving time (any status) accumulates in `nondriving_run`. Once it reaches 30 min, `drive_since_break` resets to 0. Driving resets `nondriving_run` to 0. So a 30-min pre-trip, a 1-h pickup or dropoff, a 30-min fuel stop, a break, a rest and a restart all satisfy the 30-min break requirement.

A REST or RESTART resets `drive_in_period`, `drive_since_break` and `window_start = None`. On-duty time (D and ON) adds to `cycle`. Pickup, dropoff and post-trip are allowed even if the cycle or window is exhausted, because on-duty not-driving is legal. Only driving is blocked.

Every event (`DutyEvent`) records:
- kind and status;
- start and end minutes;
- start_mile and end_mile (cumulative trip miles);
- leg_index;
- start and end coordinates, interpolated from the leg profile.

### Leg profile (`profile.py`)
Built from the route leg (Valhalla shape, each maneuver's time spread over its shape segments by distance; or the OSRM annotation arrays on the fallback):
- `coords` (lon, lat);
- `cum_miles`;
- `cum_minutes` (truck-adjusted).

Interpolation helpers:
- `mile_at_minute`;
- `minute_at_mile`;
- `coord_at_mile`.

The `road_at_mile` helper returns the route step's road name/ref so remarks can say "I 80 near Joliet, IL".

### Daily logs (`logs.py`)
1. The events are converted to absolute datetimes from `start_time`.
2. OFF is prepended from 00:00 on the start date, and appended until 24:00 on the end date.
3. Events are split at midnights.
4. Each sheet holds:
   - **segments:** merge consecutive same-status pieces, covering 0-1440;
   - **totals:** hours, summing to 24;
   - **total_miles:** driving miles that fall on that date, splitting a driving event across midnight by its profile;
   - **remarks:** one per non-driving event piece on that sheet (not the padding OFF), with its start/end minute on the sheet, the location name ("City, ST", or "I 80 near City, ST") with its `city` and `road` parts, and a note. A piece continued from the previous day gets a note ending "(cont.)". When the trip opens with driving (inspections off), the OFF→D change also gets a 1-minute remark "Start of trip / on duty", since every change of duty status needs a location (FMCSA p.17);
   - **on_duty_hours:** D + ON;
   - **cycle_hours_used:** at the end of the day (initial + trip on-duty; 0 after a restart, then accumulating);
   - **cycle_hours_available:** 70 − used, floored at 0;
   - **from_location / to_location.**
5. Locations are named by an injected `place_namer(lat, lon, road=None) -> str`, so the engine stays pure.

### Tests (pytest + hypothesis)
The property tests (`test_hos_properties.py`) check these invariants over many random trips (random leg lengths 0-3,500 mi, random speeds, cycle 0-70, random start times, both option settings):
- no driving after 11 h in a period;
- no driving after 14 h from the window start;
- ≤ 8 h driving without a ≥30-min non-driving run;
- no driving while the cycle total is ≥ 70 h (with no roll-off);
- ≤ 1,000 mi between fuel stops;
- pickup and dropoff are each exactly 60 min ON;
- events are contiguous and non-overlapping;
- total driven miles equal the route miles;
- every log sheet's segments cover 0-1440 contiguously, and totals sum to 24.00;
- per-day miles sum to the route miles;
- no mid-trip recap above 70 h: the cycle passes 70 h only after the last driving minute;
- a 10-h rest is never immediately followed by a 34-h restart;
- a restart that opens the trip lasts 34 h counting the off-duty time since midnight;
- the restart search never arrives later than the greedy plan;
- breaks, rests, restarts and fuel stops are only taken when a limit (nearly) binds.

Hand-calculated scenario tests (`test_hos_scenarios.py`) include:
- a short trip that finishes the same day;
- exactly 11 h of driving;
- a trip that needs a 34-h restart (cycle used 65);
- cycle used 70 at the start;
- current == pickup;
- a 2,500-mile multi-day trip.

## Backend API (`backend/trips/`)
- `POST /api/trips/plan/`: body is `PlanRequest`, response is `PlanResponse`.
  - **Validation:** cycle 0-70 (numbers only; booleans are rejected); start_time format, years 2000-2100; each location has lat/lon or a non-empty query. Invalid input returns 400 `ApiError` (`validation_error`); a body over Django's upload limit returns 413 (`payload_too_large`). Coordinates with no US/Canadian place within 150 mi return 422 (`unsupported_region`).
  - **Geocoding:** any `query` location is geocoded.
  - **Routing:** `route_trip` routes both legs with Valhalla truck costing (split into chunks when a leg is over the server's distance limit), falling back to one OSRM call with 3 waypoints. Unroutable input returns 422 `route_not_found`; all hosts failing returns 502 `upstream_unavailable`. If OSRM is down, a trip with a leg over 1,450 km fails too, because its split points come from OSRM.
  - The service then builds the profiles and runs the engine.
  - Every event and stop location is named from the offline dataset (plus the road ref when the stop is on a highway).
  - **Time zones:** `input.home_timezone` is the current location's zone and `home_tz_abbr` its abbreviation at the start; every `PlaceRef` gets `tz`, every event `local_start`/`local_end`/`start_tz_abbr`/`end_tz_abbr`, and every stop `local_start`/`local_end`/`local_tz_abbr`. Log sheets, `start`/`end` and the summary stay in home-terminal time.
  - The display geometry is simplified (Douglas-Peucker to about 1,500 points total). Leg geometries are simplified too.
  - Text instructions are built from the Valhalla maneuvers (mapped to OSRM's maneuver vocabulary; a roundabout exit or a "continue" on the same road folds into the line before it), or from the OSRM steps on the fallback. `services/instructions.py` is a small English generator covering depart, arrive, turn, new name, continue, merge, on ramp, off ramp, fork, end of road, roundabout/rotary (with exit number), use lane, notification, and the modifiers. Consecutive trivial steps are collapsed.
- `GET /api/geocode/?q=...`: returns `GeocodeResponse`. It requires at least 2 characters and caches results in memory. The autocomplete uses it: Photon only (no Nominatim fallback), rate-limited per IP (`GEOCODE_RATE`, default 60/min; 429 `rate_limited`). Planning is limited the same way (`PLAN_RATE`, default 20/min).
- `GET /api/reverse/?lat=..&lon=..`: returns `ReverseGeocodeResponse` from the offline dataset, for "Use my location".
- `GET /api/health/`: returns `{"status":"ok"}`.
- The view passes its total time budget (`PLAN_TIME_BUDGET_SECONDS`, 25 s by default) to the services. Valhalla with a split leg takes about 6 s, so a 3,000-mile trip plans well within the budget on a warm function.

## Frontend design
The UI is styled as a modern logistics dashboard for people who read driver logs every day.
- **Aesthetic:** clean and confident. Light theme with an ink/navy base and a single warm amber/orange "highway" accent, plus status colors per duty line:
  - OFF: slate
  - SB: indigo
  - D: emerald/green
  - ON: amber

  They are used consistently across the map markers, itinerary, charts and log legend.
- **Type:** Inter (or Geist) from Google Fonts, with tabular numbers, and a mono font for the log values.
- **Layout (desktop):** a sticky top bar with the product name ("RouteLog" or "HOS Trip Planner"), and a subtle "FMCSA 70h/8-day · Property-carrying" badge. The main area is a two-column split:
  - **Left:** a ~440 px planner panel with the trip form, and the trip summary after planning.
  - **Right:** a large map card.

  Below both is a full-width results area with tabs: **Itinerary**, **Daily Logs** (sheet count badge) and **Directions**. On mobile, stack everything with the map above the results.
- **Form:**
  - three location autocompletes, each with an icon, keyboard navigation and debounce, "Use my location" on Current, and a swap-pickup/dropoff button;
  - Current Cycle Used as a number input plus a 0-70 slider, with a helper line showing the hours left;
  - a trip start date-time, defaulting to the next 08:00 (the example trips use it too);
  - collapsible "Advanced": inspections toggle, 10-h rest status (Sleeper berth / Off duty), fuel stop minutes;
  - collapsible "Log sheet details" (driver, co-driver, carrier, main office, home terminal, truck #, trailer #, shipping doc), persisted in `localStorage`. They start filled with the FMCSA guide's own sample identity (John E. Doe, PDF p.19), labelled as sample data, so every sheet is complete out of the box; drivers edit or clear them;
  - "Try an example" chips that fill realistic trips (short, cross-country, and near the cycle limit);
  - a primary "Plan trip" button with a loading state.
- **Share links and history:** a plan writes its request to the URL (`?from=Label@lat,lon&pickup=…&to=…&cycle=…&start=YYYY-MM-DDTHH:MM`, plus `insp=1`, `rest=OFF`, `fuel=N` only when not default; a location without coordinates is plain text and is geocoded). Responses are cached in `sessionStorage` (`routelog.plan.v2:<query>`), so reload, Back and Forward restore a plan without an API call; an uncached link re-plans with a loading state. A "Copy share link" button copies the URL, and Back from results returns to the form.
- **Map:**
  - the route line with leg 0 and leg 1 visually distinct;
  - start (current), pickup and dropoff pins;
  - stop markers by kind (fuel, break, rest, restart, pre/post-trip), with lucide icons in colored circles;
  - hover/click popups showing the time window, duration, location and mile marker. Popups stack above markers and map controls and pick the side that fits;
  - a legend, and fit-to-route (first in tab order);
  - selecting an itinerary item flies to its stop.
- **Summary:**
  - a routing badge: "Truck-routed (Valhalla)" or "Car network (OSRM fallback)" from `route.truck_routing`;
  - stat tiles: total miles, driving, on-duty total (incl. driving), trip duration (d h m), log sheets, fuel stops, 10-hr rests, 34-hr restarts, 30-min breaks, and cycle hours left at arrival. Durations in the UI use one format (`39h 10m`);
  - a compact horizontal "duty timeline bar" for the whole trip, colored by status and scaled by time;
  - warnings (e.g. a 34-h restart was required).
- **Itinerary:** a vertical timeline grouped by day (Day N · date). Each row shows:
  - the time range and duration;
  - a status chip;
  - the activity label and location;
  - miles for driving rows;
  - the stop's local time and zone ("19:30 MDT local") where it differs from home-terminal time, and an "Outside typical dock hours" chip for a pickup or drop-off between 22:00 and 05:00 local.

  Each day card notes when a calendar day holds more than 11:00 of driving across two duty periods ("2 duty periods today: 11:00 + 0:45 driving; each ≤ 11 h (§395.3)"); the same note appears on that log sheet.
- **Daily Logs:** FMCSA-style SVG sheets (see below), with a day switcher (pills) and "Show all". The toolbar has Print / Save as PDF (print CSS, one sheet per landscape page) and a Download menu for the current sheet as SVG or PNG (fonts embedded). On phones the sheet fits the width by default, with an "Actual size" toggle that scrolls sideways.
- **Directions:** per-leg collapsible lists with maneuver icons, text and distance, plus a leg header with distance and time. City-street steps before the first and after the last interstate fold into a "Local streets" row; interstate steps get an `I-55` badge.
- **Place names:** one display form everywhere (`lib/format.ts` `placeLabel`): "St. Louis", "I-44".
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
The sheet is modelled on the blank paper log and the FMCSA form (PDF p.15/19). It uses a landscape viewBox of about 1100×850, stays crisp at any width, and is print-ready.

- **Title block:**
  - "DRIVER'S DAILY LOG" / "(ONE CALENDAR DAY — 24 HOURS)" and "U.S. DEPARTMENT OF TRANSPORTATION";
  - the ORIGINAL/DUPLICATE retention notes;
  - the date (month/day/year) and a sheet "Day N of M";
  - From/To;
  - Total Miles Driving Today;
  - Total Mileage Today (same value; single driver);
  - Truck/Tractor & Trailer numbers;
  - Name of Carrier, Main Office Address and Home Terminal Address;
  - Driver signature line, left blank for a wet signature (the app never signs), and the driver name printed beside it;
  - Co-driver (blank line when empty). Empty header fields stay blank underlines.
- **Grid:** a black header bar with "Mid-night, 1…11, Noon, 1…11, Mid-night", 24 hour columns and 4 rows labeled "1. Off Duty", "2. Sleeper Berth", "3. Driving" and "4. On Duty (not driving)".
  - Each hour has 15-min ticks (short) and a 30-min tick (longer), as in the blank form.
  - A "Total Hours" column on the right shows each row's hours as `h:mm` (whole minutes, largest-remainder rounded so rows add up exactly) and a double-underlined grand total `24:00`.
- **Duty line:** a continuous "pen" path (dark blue ink, about 2.5 px) through the middle of the active row for each segment, with vertical connectors at every status change.
- **Remarks:** a second hour ruler under the grid, labeled "REMARKS".
  - Each remark gets a bracket (a cup shape) under its start-end span, and its "City, ST — note" text rotated about −45° from the start point, as in the FMCSA completed log.
  - Labels are staggered to avoid overlap when remarks are close together. Remarks at the same place starting within 60 min share one label, activities joined with " / " and abbreviated ("I-44 near Joplin, MO — Post-trip / 10-h rest (SB)"), each keeping its bracket. A long label wraps to the place and the activity on the next line, then shrinks (floor 6.5 px); remarks are never truncated. A remark names the city and state, and outside a city the highway too ("I-70 near Chapman, KS", FMCSA p.17; the router gives no mileposts). Leaders are drawn under the labels, and labels carry a paper halo.
- **Shipping documents:** "DVL or Manifest No." and "Shipper & Commodity" lines, filled from the header details.
- **Recap (70 Hour / 8 Day):**
  - on duty today (lines 3 & 4);
  - A: cycle hours used, including today;
  - B: hours available tomorrow (70 − A, floored at 0);
  - C: cycle hours used in the last 8 days, including today (the same conservative value as A, since no per-day history is given; a footnote says so);
  - the footnote "*34 consecutive hours off duty resets to 70 available", with "34-hr restart taken" if one ended that day (including one ending exactly at 24:00, where A resets to 0), or "in progress" if it runs past midnight.
- **Visual:** paper-white background with a subtle border, form lines in near-black, and filled-in values in blue "ink" (mono or handwriting-ish font).

## Engine public interface (between the engine and the API layer)

```python
# backend/trips/hos/profile.py
@dataclass(frozen=True)
class RouteStep:            # one routing step (Valhalla maneuver or OSRM step) within a leg, leg-relative miles
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
    include_inspections: bool = False  # off by default: the brief lists only pickup, drop-off and fuel
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

def plan_events(legs, cycle_used_hours, options, *, prior_off_duty_minutes=0) -> list[DutyEvent]   # lower-level, used by tests
# prior_off_duty_minutes: whole minutes off duty just before the start (0-2039); a restart at minute 0 counts them.
# build_plan passes the minutes since midnight of start_time.
```
The API layer (`planner_service.py` + `services/valhalla.py`, with `services/routing.py` for the OSRM fallback) builds the `LegProfile`s from the Valhalla shape and maneuvers (or from OSRM's `legs[i].annotation.distance/duration`, geometry coordinates and steps) and applies the 65 mph truck cap when it builds `seg_minutes`. It calls `build_plan` and adds `input` and `route` to form the `PlanResponse`. The warnings from `build_plan` include things like "34-hour restart required on day 1: only 27h 15m of the 70-hour cycle is left and the rest of the trip needs more (assumes none of the hours already used roll off during the trip)." or "34-hour restart required before driving: the 70-hour cycle is already used up at the start; it counts the 8h off duty since midnight, so it lasts 26h". The roll-off clause appears only when the trip's own work to its last drive fits in 70 h, i.e. when the no-roll-off assumption is what forces the restart. The API layer may add routing warnings (the OSRM fallback, a location far from a road, a zero-length leg).
