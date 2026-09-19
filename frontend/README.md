# RouteLog frontend

Vite 8, React 19, TypeScript, Tailwind CSS v4, MapLibre GL (via `react-map-gl/maplibre`) and lucide-react. See the [root README](../README.md) for the full picture.

```bash
npm install
npm run dev      # http://localhost:5173; proxies /api to 127.0.0.1:8000
npm run build    # tsc type-check + production build into dist/
npm run lint     # oxlint
npm test         # vitest: log-sheet geometry, formatters, directions, validation
```

## Configuration

- `VITE_API_BASE_URL` (see [`.env.example`](.env.example)): the backend origin. Leave it empty to call `/api` on the same origin. That is the Vite dev proxy locally, and the `/api/*` rewrite in [`vercel.json`](vercel.json) in production.
- `vercel.json` proxies `/api/(.*)` to the deployed backend (`https://eld-trip-planner-api-ten.vercel.app`); point it at your own backend when deploying a copy. The regex form keeps Django's trailing slashes intact. Every other path falls back to `index.html`.

## Offline demo

Add a query parameter to review the UI without a backend. The fixtures are responses recorded from the live API (OSRM routing and the HOS engine). They are loaded lazily and never ship in the main bundle.

- `?demo=1`: Chicago, IL → St. Louis, MO → Dallas, TX, with 10 h of cycle used (2 log sheets).
- `?demo=restart`: Seattle, WA → Denver, CO → Houston, TX, with 60 h used, which needs a 34-hour restart (5 log sheets).

## Layout

| Path | What it holds |
|---|---|
| `src/types/api.ts` | The shared JSON contract with the Django API (snake_case, source of truth) |
| `src/lib/api.ts` | Typed fetch client that turns every failure into an `ApiRequestError` |
| `src/components/planner/` | Trip form: location comboboxes, cycle input, advanced options, log-header fields, example trips |
| `src/components/map/` | MapLibre map on OpenFreeMap tiles: route legs, endpoint pins, stop markers, popups, legend |
| `src/components/summary/` | Stat tiles and the whole-trip duty timeline bar |
| `src/components/results/` | Results tabs: itinerary by day, directions per leg |
| `src/components/logsheet/` | FMCSA driver's daily log as SVG (`LogSheet`), day switcher, print and SVG/PNG export (`DailyLogsView`) |
| `src/mocks/` | Offline demo client and recorded fixtures |
