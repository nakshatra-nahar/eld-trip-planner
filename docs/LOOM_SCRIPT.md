# Loom talk track (about 4.5 minutes)

The video has two parts: a demo of the live app (about 2.5 minutes), then a code walkthrough (about 2 minutes). Timestamps are targets. **Do** is what to click. **Say** is a suggested line; paraphrase freely.

Before recording:
- Open the live app in one tab and `?demo=restart` in a second tab as a backup if the routing servers are slow.
- Open the repository in the editor with these files in tabs: `backend/trips/hos/rules.py`, `planner.py`, `audit.py`, `logs.py`, `backend/trips/services/valhalla.py`, `backend/trips/tests/test_hos_properties.py`, `frontend/src/components/logsheet/geometry.ts`.
- "Log sheet details" start filled with the FMCSA guide's sample identity (John E. Doe), so the sheets look complete; change them if you like. The browser remembers them.
- Use a browser window about 1440 px wide, zoomed to 100%.

---

## Part 1: the app (0:00-2:30)

### 0:00-0:15 · Intro
**Do:** Show the empty state of the live app.
**Say:** "This is RouteLog, my submission for the Spotter full-stack assessment. You give it a current location, a pickup, a drop-off and the hours already used in your 70-hour cycle. It plans a trip that follows the FMCSA hours-of-service rules and draws the driver's daily log for every day of the trip."

### 0:15-0:45 · The form
**Do:** Type "Chic" in Current location and pick Chicago, IL with the keyboard. Point out "Use my location" and the swap button. Drag the cycle slider and show the hours-left helper. Open **Advanced**.
**Say:** "Autocomplete is limited to the US and Canada, and every field works from the keyboard. The cycle input tells you how many hours you have left. Under Advanced you can turn inspections off, log 10-hour rests as sleeper berth or off duty, and change how long a fuel stop takes. The defaults follow the brief: fuel at least every 1,000 miles, and one hour each for pickup and drop-off."

### 0:45-1:15 · Plan a hard trip
**Do:** Click the **Near cycle limit** example chip (Kansas City → St. Louis → Atlanta, 58 h used), then **Plan trip**. While it loads, point at the skeletons.
**Say:** "I'll pick a hard case: 58 of 70 hours already used. The backend geocodes the stops, routes both legs with Valhalla's truck profile, so the route stays on truck-legal roads, and runs the HOS engine, usually in about two seconds. If the truck router is down, it falls back to OSRM and the badge says so."

### 1:15-1:45 · Map and summary
**Do:** Point at the "Truck-routed (Valhalla)" badge, the summary tiles and the duty timeline bar, then at the warning about the 34-hour restart. On the map, hover a stop marker to show its popup with home-terminal and local time. Click a row in the **Itinerary** tab so the map flies to that stop. Click **Copy share link**, then reload the page.
**Say:** "The summary shows total miles, driving and on-duty hours, and how much cycle is left at arrival. The colored bar is the whole trip by duty status. With twelve hours left, the driver picks up in St. Louis and runs out of cycle near Monteagle, Tennessee, on day 1, so the planner inserts a 34-hour restart and says why. It doesn't just restart as late as possible: it also tries the restart at the trip start and in place of each 10-hour rest, and keeps whichever arrives first. On a Los Angeles to New York run that saves about 11 hours. Every stop sits at the exact point on the route where its limit is reached. Times are home-terminal time, as on the logs, and stops in other zones also show local time, with a warning when a pickup or drop-off lands outside dock hours. The plan lives in the URL, so a reload or a shared link brings it straight back."

### 1:45-2:20 · The log sheets
**Do:** Open **Daily Logs**. Step through the day pills, then click **Show all**. Zoom into one sheet's grid and remarks. Click **Print / Save as PDF** and show the preview, then cancel.
**Say:** "This is the part a safety manager actually checks. There's one sheet per calendar day, drawn in SVG to match the FMCSA paper form. The duty line runs through the four rows, with a connector at every change of status. The row totals always add up to exactly 24. Remarks brackets mark each stop and name the city and state, or the highway, as in 'I 44 near Joplin, MO'. The recap at the bottom shows the 70-hour cycle, including the restart. The sheets print one per landscape page, or download as SVG or PNG."

### 2:20-2:30 · Directions and mobile
**Do:** Open **Directions** and expand a leg. Then narrow the window, or open device mode, to show the stacked mobile layout.
**Say:** "The turn-by-turn directions come from Valhalla's truck maneuvers. If the route falls back to OSRM, my own English instruction generator writes them instead. City streets are folded so the interstates stand out. The whole app works at phone width."

---

## Part 2: the code (2:30-4:30)

### 2:30-2:50 · Architecture
**Do:** Show the mermaid diagram in the root `README.md`.
**Say:** "There's a React and MapLibre frontend, and a stateless Django API that calls Valhalla for truck routing, OSRM as the fallback, and Photon for search. The core is a pure-Python HOS engine with no Django or network imports, so it's fast and easy to test. Place names and time zones come from an offline GeoNames index, so we never call a rate-limited reverse geocoder."
**Do:** Open `backend/trips/services/valhalla.py` and show `route_trip`.
**Say:** "The public Valhalla server caps a request at 1,500 kilometres, so long legs are split on an interstate and stitched back together. Any failure drops the whole trip to OSRM, and the response says which router it used."

### 2:50-3:30 · The engine
**Do:** In `backend/trips/hos/rules.py`, scroll the constants with their FMCSA page comments. Then in `planner.py`, show `_Planner._drive_step`.
**Say:** "Every limit is a named constant in integer minutes, with the page of the FMCSA guide it comes from. The planner is a small state machine. At each step it checks, in priority order: cycle exhausted means a 34-hour restart; 11 hours driven or the 14-hour window closed means a 10-hour rest; 8 hours driving means a 30-minute break; then fuel. Otherwise it drives until the first limit binds. There are a few details from the guide: any 30 consecutive non-driving minutes count as the break, so a pickup or a long fuel stop resets that clock. Driving stops at the limits, but on-duty work doesn't, so a drop-off can always be finished."
**Do:** Scroll to `_optional_restart` and `plan_drives`.
**Say:** "When the trip won't fit in the cycle, the greedy plan restarts as late as possible. `plan_drives` also replans with the restart at the start and at each 10-hour rest where a fresh cycle would cover the rest of the trip, and keeps the earliest arrival. A restart at the start counts the hours off since midnight, so for an 8 a.m. start it only needs 26 more hours."
**Do:** Scroll to `_fuel_room` and `LegDrive.progress_at_leg_mile`.
**Say:** "Stops are placed on the real route profile, and speeds are capped at 65 mph for a truck. Working in whole minutes means every sheet sums to exactly 1,440."

### 3:30-4:10 · How I know it's accurate
**Do:** Open `audit.py` and show `audit_events`. Then open `test_hos_properties.py` and show `check_trip` and `assert_no_premature_stops`.
**Say:** "Accuracy was my top priority, so I didn't trust the planner to grade itself. `audit.py` is an independent auditor. It reads only the finished list of events and re-derives every clock from the rules: the 11-hour, 14-hour, 8-hour, 70-hour and 1,000-mile limits. `audit_plan` checks that every log sheet covers 24 hours and that the totals and miles add up. Then Hypothesis generates hundreds of random trips, from zero to 3,500 miles per leg, with mixed speeds, any cycle value from 0 to 70 and every option. Every plan has to pass the auditor, and the planner may not stop early. There are also hand-calculated scenario tests, like the 34-hour restart and a trip that ends exactly at midnight. Finally, I ran a separate checker that reads only the API's JSON over real routed trips, and it rechecks every limit and that each sheet matches the timeline minute by minute."

### 4:10-4:25 · The log sheet renderer
**Do:** In `frontend/src/components/logsheet/geometry.ts`, show `buildDutyPath` and `layoutRemarks`.
**Say:** "On the frontend, the log sheet is plain SVG, which keeps it sharp at any size and easy to print. `buildDutyPath` draws the duty line as one continuous path. `layoutRemarks` staggers the angled remark labels so stops close together don't overlap."

### 4:25-4:30 · Close
**Do:** Show the README's Limitations section.
**Say:** "What I'd build next is in the README: rolling 70-hour history per day, the split sleeper berth, real truck dimensions, and real truck stops for fuel and rest. Thanks for watching."
