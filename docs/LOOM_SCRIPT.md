# Loom talk track (about 4.5 minutes)

The video has two parts: a demo of the live app (about 2.5 minutes), then a code walkthrough (about 2 minutes). Timestamps are targets. **Do** is what to click. **Say** is a suggested line; paraphrase freely.

Before recording:
- Open the live app in one tab and `?demo=restart` in a second tab as a backup if OSRM is slow.
- Open the repository in the editor with these files in tabs: `backend/trips/hos/rules.py`, `planner.py`, `audit.py`, `logs.py`, `backend/trips/tests/test_hos_properties.py`, `frontend/src/components/logsheet/geometry.ts`.
- Fill in "Log sheet details" once (driver, carrier, truck number), so the sheets look complete. The browser remembers them.
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
**Do:** Click the **Near cycle limit** example chip (Kansas City → St. Louis → Atlanta, 64 h used), then **Plan trip**. While it loads, point at the skeletons.
**Say:** "I'll pick a hard case: 64 of 70 hours already used. The backend geocodes the stops, gets one OSRM route with both legs, and runs the HOS engine, usually in a second or two."

### 1:15-1:45 · Map and summary
**Do:** Point at the summary tiles and the duty timeline bar, then at the warning about the 34-hour restart. On the map, hover a stop marker to show its popup. Click a row in the **Itinerary** tab so the map flies to that stop.
**Say:** "The summary shows total miles, driving and on-duty hours, and how much cycle is left at arrival. The colored bar is the whole trip by duty status. With six hours left, the driver runs out of cycle partway through, so the planner inserts a 34-hour restart and says why. Every stop sits at the exact point on the route where its limit is reached, and the itinerary is linked to the map."

### 1:45-2:20 · The log sheets
**Do:** Open **Daily Logs**. Step through the day pills, then click **Show all**. Zoom into one sheet's grid and remarks. Click **Print / Save as PDF** and show the preview, then cancel.
**Say:** "This is the part a safety manager actually checks. There's one sheet per calendar day, drawn in SVG to match the FMCSA paper form. The duty line runs through the four rows, with a connector at every change of status. The row totals always add up to exactly 24. Remarks brackets mark each stop and name the city and state, or the highway, as in 'I 44 near Joplin, MO'. The recap at the bottom shows the 70-hour cycle, including the restart. The sheets print one per landscape page, or download as SVG or PNG."

### 2:20-2:30 · Directions and mobile
**Do:** Open **Directions** and expand a leg. Then narrow the window, or open device mode, to show the stacked mobile layout.
**Say:** "The turn-by-turn directions come from my own English generator built on the OSRM maneuvers. The whole app works at phone width."

---

## Part 2: the code (2:30-4:30)

### 2:30-2:50 · Architecture
**Do:** Show the mermaid diagram in the root `README.md`.
**Say:** "There's a React and MapLibre frontend, and a stateless Django API that calls OSRM and Photon. The core is a pure-Python HOS engine with no Django or network imports, so it's fast and easy to test. Place names in the remarks come from an offline GeoNames index, so we never call a rate-limited reverse geocoder."

### 2:50-3:30 · The engine
**Do:** In `backend/trips/hos/rules.py`, scroll the constants with their FMCSA page comments. Then in `planner.py`, show `_Planner._drive_step`.
**Say:** "Every limit is a named constant in integer minutes, with the page of the FMCSA guide it comes from. The planner is a small state machine. At each step it checks, in priority order: cycle exhausted means a 34-hour restart; 11 hours driven or the 14-hour window closed means a 10-hour rest; 8 hours driving means a 30-minute break; then fuel. Otherwise it drives until the first limit binds. There are a few details from the guide: any 30 consecutive non-driving minutes count as the break, so a pickup or a long fuel stop resets that clock. Driving stops at the limits, but on-duty work doesn't, so a drop-off can always be finished."
**Do:** Scroll to `_fuel_room` and `LegDrive.progress_at_leg_mile`.
**Say:** "Stops are placed on the real route profile, and speeds are capped at 65 mph for a truck. Working in whole minutes means every sheet sums to exactly 1,440."

### 3:30-4:10 · How I know it's accurate
**Do:** Open `audit.py` and show `audit_events`. Then open `test_hos_properties.py` and show `check_trip` and `assert_no_premature_stops`.
**Say:** "Accuracy was my top priority, so I didn't trust the planner to grade itself. `audit.py` is an independent auditor. It reads only the finished list of events and re-derives every clock from the rules: the 11-hour, 14-hour, 8-hour, 70-hour and 1,000-mile limits. `audit_plan` checks that every log sheet covers 24 hours and that the totals and miles add up. Then Hypothesis generates hundreds of random trips, from zero to 3,500 miles per leg, with mixed speeds, any cycle value from 0 to 70 and every option. Every plan has to pass the auditor, and the planner may not stop early. There are also hand-calculated scenario tests, like the 34-hour restart and a trip that ends exactly at midnight."

### 4:10-4:25 · The log sheet renderer
**Do:** In `frontend/src/components/logsheet/geometry.ts`, show `buildDutyPath` and `layoutRemarks`.
**Say:** "On the frontend, the log sheet is plain SVG, which keeps it sharp at any size and easy to print. `buildDutyPath` draws the duty line as one continuous path. `layoutRemarks` staggers the angled remark labels so stops close together don't overlap."

### 4:25-4:30 · Close
**Do:** Show the README's Limitations section.
**Say:** "What I'd build next is in the README: rolling 70-hour history per day, time zones, the split sleeper berth, and truck-specific routing. Thanks for watching."
