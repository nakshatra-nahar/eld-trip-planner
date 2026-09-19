"""English turn-by-turn instructions from OSRM route steps.

Our own compact take on OSRM's maneuver vocabulary
(http://project-osrm.org/docs/v5.24.0/api/#stepmaneuver-object): every maneuver type
(depart, arrive, turn, new name, continue, merge, on/off ramp, ramp, fork, end of road,
use lane, roundabout, rotary, roundabout turn, exit roundabout/rotary, notification)
and every modifier (uturn, sharp/slight left/right, left, right, straight).

``build_instructions`` also collapses trivial steps (a road merely changing its name,
lane hints, "continue straight" on the same road) into the preceding instruction so
the directions list stays readable for a 1,000-mile leg.
"""

from __future__ import annotations

from typing import Any

METERS_PER_MILE = 1609.344
TRUCK_MAX_MPS = 65 * METERS_PER_MILE / 3600  # 65 mph cap, as in the HOS profile

_DIRECTIONS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]
_ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"]

# Maneuvers that never change which road you are on, so they can be folded into the
# previous instruction when they keep going (roughly) straight.
_TRIVIAL_TYPES = {"new name", "continue", "notification", "use lane", "exit roundabout", "exit rotary"}
_STRAIGHTISH = {"", "straight", "slight left", "slight right"}
_SHORT_STEP_M = 80.0  # a <80 m same-road hop is noise in a truck route


def compass(bearing: float | int | None) -> str:
    """Bearing in degrees -> "north", "southwest", ... ("" if unknown)."""
    if bearing is None:
        return ""
    return _DIRECTIONS[int(((float(bearing) % 360) + 22.5) // 45) % 8]


def ordinal(n: int) -> str:
    if 1 <= n <= len(_ORDINALS):
        return _ORDINALS[n - 1]
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _refs(ref: str | None) -> list[str]:
    return [r.strip() for r in (ref or "").split(";") if r.strip()]


def road_label(step: dict[str, Any]) -> str:
    """Short road identifier for the ``road`` field: first ref ("I 55"), else the name."""
    refs = _refs(step.get("ref"))
    return refs[0] if refs else (step.get("name") or "").strip()


def way_name(step: dict[str, Any]) -> str:
    """Readable road name: "Stevenson Expressway (I 55)", "I 55 / US 40", "Main Street"."""
    name = (step.get("name") or "").strip()
    refs = _refs(step.get("ref"))
    ref = " / ".join(refs)
    if name and ref and ref.replace(" ", "") not in name.replace(" ", ""):
        return f"{name} ({ref})"
    return name or ref


def _destinations(step: dict[str, Any], limit: int = 2) -> str:
    """OSRM "I 55 South, I 64: Saint Louis, Springfield" -> "I 55 South: Saint Louis, Springfield"."""
    raw = (step.get("destinations") or "").strip()
    if not raw:
        return ""
    refs_part, _, places_part = raw.partition(":")
    refs = [r.strip() for r in refs_part.split(",") if r.strip()][:limit]
    places = [p.strip() for p in places_part.split(",") if p.strip()][:limit]
    if refs and places:
        return f"{', '.join(refs)}: {', '.join(places)}"
    return ", ".join(refs or places)


def _side(modifier: str) -> str:
    return "left" if "left" in modifier else "right" if "right" in modifier else ""


def _turn_phrase(modifier: str) -> str:
    """Verb phrase for a directional change: "Turn left", "Make a U-turn", "Go straight"."""
    if modifier == "uturn":
        return "Make a U-turn"
    if modifier in ("straight", ""):
        return "Go straight"
    return f"Turn {modifier}"


def _onto(way: str) -> str:
    return f" onto {way}" if way else ""


def _toward(step: dict[str, Any]) -> str:
    dest = _destinations(step)
    return f" toward {dest}" if dest else ""


def instruction_text(step: dict[str, Any], waypoint_label: str | None = None) -> str:
    """Render one OSRM step as an English sentence (without trailing period)."""
    man = step.get("maneuver") or {}
    kind = man.get("type") or "turn"
    mod = man.get("modifier") or ""
    way = way_name(step)
    exit_n = man.get("exit")
    side = _side(mod)

    if kind == "depart":
        heading = compass(man.get("bearing_after"))
        text = f"Head {heading}" if heading else "Depart"
        return text + (f" on {way}" if way else "")

    if kind == "arrive":
        target = waypoint_label or "your destination"
        return f"Arrive at {target}" + (f", on the {side}" if side else "")

    if kind in ("roundabout", "rotary"):
        place = (step.get("rotary_name") or "").strip() if kind == "rotary" else ""
        noun = place or ("the traffic circle" if kind == "rotary" else "the roundabout")
        if exit_n:
            return f"Enter {noun} and take the {ordinal(int(exit_n))} exit" + _onto(way)
        return f"Enter {noun} and exit" + _onto(way)

    if kind == "roundabout turn":
        if exit_n:
            return f"At the roundabout, take the {ordinal(int(exit_n))} exit" + _onto(way)
        return f"At the roundabout, {_turn_phrase(mod).lower()}" + _onto(way)

    if kind in ("exit roundabout", "exit rotary"):
        noun = "traffic circle" if kind == "exit rotary" else "roundabout"
        return f"Exit the {noun}" + _onto(way)

    if kind == "merge":
        return (f"Merge {side}" if side else "Merge") + _onto(way)

    if kind in ("on ramp", "ramp"):
        text = f"Take the ramp on the {side}" if side else "Take the ramp"
        return text + (_toward(step) or _onto(way))

    if kind == "off ramp":
        exits = (step.get("exits") or "").split(";")[0].strip()
        text = f"Take exit {exits}" if exits else "Take the exit"
        if side:
            text += f" on the {side}"
        return text + (_toward(step) or _onto(way))

    if kind == "fork":
        text = f"Keep {side} at the fork" if side else "Keep straight at the fork"
        return text + (_toward(step) or _onto(way))

    if kind == "end of road":
        return f"{_turn_phrase(mod)} at the end of the road" + _onto(way)

    if kind == "use lane":
        if side:
            return f"Keep {side}" + (f" to stay on {way}" if way else "")
        return "Continue straight" + (f" on {way}" if way else "")

    if kind in ("continue", "new name", "notification"):
        if mod == "uturn":
            return "Make a U-turn" + _onto(way)
        if mod in ("", "straight"):
            return "Continue" + (f" onto {way}" if kind == "new name" and way else f" on {way}" if way else " straight")
        if mod.startswith("slight"):
            return f"Bear {side}" + _onto(way)
        return f"Continue {mod}" + _onto(way)

    # "turn" and any unknown future type.
    return _turn_phrase(mod) + _onto(way)


def _truck_seconds(step: dict[str, Any]) -> float:
    dist = float(step.get("distance") or 0.0)
    return max(float(step.get("duration") or 0.0), dist / TRUCK_MAX_MPS)


def _same_road(step: dict[str, Any], prev_step: dict[str, Any]) -> bool:
    """True if ``step`` stays on the road of ``prev_step`` (shared ref, or same bare name)."""
    refs, prev_refs = set(_refs(step.get("ref"))), set(_refs(prev_step.get("ref")))
    if refs or prev_refs:
        return bool(refs & prev_refs)
    name = (step.get("name") or "").strip()
    return not name or name == (prev_step.get("name") or "").strip()


def _is_trivial(step: dict[str, Any], prev_step: dict[str, Any]) -> bool:
    """Can ``step`` be folded into the instruction created by ``prev_step``?

    Only for maneuvers that keep going (roughly) straight: a road that merely changes
    its name while keeping its ref (e.g. memorial-highway stretches of an interstate),
    an unnamed continuation, a lane hint, or a tiny same-direction hop.
    """
    man = step.get("maneuver") or {}
    if man.get("type") not in _TRIVIAL_TYPES or (man.get("modifier") or "") not in _STRAIGHTISH:
        return False
    no_label = not road_label(step)
    return no_label or _same_road(step, prev_step) or float(step.get("distance") or 0.0) < _SHORT_STEP_M


_ROUNDABOUT_TYPES = {"roundabout", "rotary", "roundabout turn"}
_EXIT_TYPES = {"exit roundabout", "exit rotary"}


def build_instructions(steps: list[dict[str, Any]], arrive_label: str | None = None) -> list[dict[str, Any]]:
    """Turn one OSRM leg's steps into ``Instruction`` dicts (see frontend api.ts).

    ``arrive_label`` names the leg's destination in the final "Arrive at ..." line.
    """
    out: list[dict[str, Any]] = []
    for step in steps:
        man = step.get("maneuver") or {}
        kind = man.get("type") or "turn"
        dist_m = float(step.get("distance") or 0.0)
        secs = _truck_seconds(step)
        prev = out[-1] if out else None

        if prev is not None and kind in _EXIT_TYPES and prev["maneuver"] in _ROUNDABOUT_TYPES:
            # "Enter the roundabout ..." already says which exit; name the road it leads to.
            if road_label(step) and road_label(step) != prev["road"]:
                renamed = {**prev["_step"], "name": step.get("name"), "ref": step.get("ref")}
                prev["text"] = instruction_text(renamed)
                prev["road"] = road_label(step)
            prev["_last"] = step
            prev["_m"] += dist_m
            prev["_s"] += secs
            continue

        if prev is not None and kind not in ("depart", "arrive") and _is_trivial(step, prev["_last"]):
            prev["_last"] = step
            prev["_m"] += dist_m
            prev["_s"] += secs
            continue

        loc = man.get("location") or [0.0, 0.0]
        out.append(
            {
                "text": instruction_text(step, arrive_label if kind == "arrive" else None),
                "maneuver": kind,
                "modifier": man.get("modifier") or "",
                "road": road_label(step),
                "location": [round(float(loc[0]), 6), round(float(loc[1]), 6)],
                "_m": dist_m,
                "_s": secs,
                "_step": step,  # step that created this instruction
                "_last": step,  # latest step folded into it (the road we are on now)
            }
        )
    for ins in out:
        del ins["_step"], ins["_last"]
        ins["distance_miles"] = round(ins.pop("_m") / METERS_PER_MILE, 2)
        ins["duration_minutes"] = round(ins.pop("_s") / 60.0, 1)
    return out
