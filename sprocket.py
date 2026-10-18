"""Sprocket: offline bicycle gearing calculator driven by a plain-text drivetrain file.

Run `python3 sprocket.py --help` for the list of commands.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from dataclasses import dataclass

MM_PER_INCH = 25.4
KM_PER_MILE = 1.609344
SPIN_LIMIT_RPM = 120
GRIND_LIMIT_RPM = 60
KEYS = ("name", "wheel", "cadence", "chainrings", "cassette", "tolerance", "gap")
REQUIRED = ("wheel", "chainrings", "cassette")

# Approximate outside circumferences in mm. Measure your own wheel for accuracy.
WHEEL_PRESETS = {
    "700x23c": 2096,
    "700x25c": 2105,
    "700x28c": 2136,
    "700x32c": 2155,
    "26x1.95": 2070,
    "27.5x2.1": 2079,
}


class GearError(Exception):
    """Carries every problem found in a drivetrain file, one 'line N: ...' string each."""

    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = list(errors)


@dataclass
class Drivetrain:
    name: str
    wheel_mm: float
    cadence: float
    chainrings: list
    cassette: list
    tolerance: float
    gap: float


@dataclass(frozen=True)
class Gear:
    ring: int
    cog: int
    ratio: float
    inches: float
    dev_m: float
    kmh: float

    @property
    def mph(self) -> float:
        return self.kmh / KM_PER_MILE


# ---------------------------------------------------------------- parsing

def _name(value):
    if not value:
        raise ValueError("name must not be empty")
    return value


def _wheel(value):
    key = value.lower()
    if key in WHEEL_PRESETS:
        return float(WHEEL_PRESETS[key])
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*mm", key)
    if not match:
        raise ValueError(
            f"unknown wheel {value!r}; use a preset (run 'sprocket wheels') or a length like 2105mm"
        )
    mm = float(match.group(1))
    if not 500 <= mm <= 3000:
        raise ValueError(f"wheel circumference {mm:g} mm is out of range (500-3000)")
    return mm


def _ranged(lo, hi, what):
    def convert(value):
        try:
            number = float(value)
        except ValueError:
            raise ValueError(f"{what} must be a number, got {value!r}") from None
        if not lo <= number <= hi:
            raise ValueError(f"{what} must be between {lo:g} and {hi:g}, got {value}")
        return number

    return convert


def _teeth(what):
    def convert(value):
        tokens = [token for token in re.split(r"[\s,]+", value) if token]
        if not tokens:
            raise ValueError(f"{what} needs at least one tooth count")
        teeth = []
        for token in tokens:
            if not re.fullmatch(r"\d+", token):
                raise ValueError(f"{token!r} is not a tooth count in {what}")
            count = int(token)
            if not 1 <= count <= 100:
                raise ValueError(f"{count} teeth is out of range in {what} (1-100)")
            teeth.append(count)
        return teeth

    return convert


CONVERTERS = {
    "name": _name,
    "wheel": _wheel,
    "cadence": _ranged(1, 250, "cadence"),
    "chainrings": _teeth("chainrings"),
    "cassette": _teeth("cassette"),
    "tolerance": _ranged(0, 10, "tolerance"),
    "gap": _ranged(0.1, 100, "gap"),
}


def parse(text: str) -> Drivetrain:
    """Parse a drivetrain file. Raises GearError listing every problem found."""
    found = []  # (line number, message); missing keys have no line and sort last
    seen = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        body = raw.split("#", 1)[0].strip()
        if not body:
            continue
        if ":" not in body:
            found.append((lineno, f"line {lineno}: expected 'key: value', got {body!r}"))
            continue
        key, _, value = body.partition(":")
        key = key.strip().lower()
        if key not in KEYS:
            found.append((lineno, f"line {lineno}: unknown key {key!r}"))
        elif key in seen:
            found.append((lineno, f"line {lineno}: duplicate key {key!r} (first on line {seen[key][1]})"))
        else:
            seen[key] = (value.strip(), lineno)

    parsed = {"cadence": 90.0, "tolerance": 0.5, "gap": 15.0}
    for key, (value, lineno) in seen.items():
        try:
            parsed[key] = CONVERTERS[key](value)
        except ValueError as exc:
            found.append((lineno, f"line {lineno}: {exc}"))

    for key in REQUIRED:
        if key not in seen:
            found.append((math.inf, f"missing required key {key!r}"))

    if found:
        raise GearError([message for _, message in sorted(found, key=lambda item: item[0])])
    return Drivetrain(
        name=parsed.get("name", "unnamed"),
        wheel_mm=parsed["wheel"],
        cadence=parsed["cadence"],
        chainrings=parsed["chainrings"],
        cassette=parsed["cassette"],
        tolerance=parsed["tolerance"],
        gap=parsed["gap"],
    )


def load(path: str) -> Drivetrain:
    with open(path, encoding="utf-8") as handle:
        return parse(handle.read())


# ---------------------------------------------------------------- maths

def wheel_diameter_in(wheel_mm: float) -> float:
    return wheel_mm / math.pi / MM_PER_INCH


def make_gear(ring: int, cog: int, wheel_mm: float, cadence: float) -> Gear:
    ratio = ring / cog
    dev_m = ratio * wheel_mm / 1000
    return Gear(
        ring=ring,
        cog=cog,
        ratio=ratio,
        inches=ratio * wheel_diameter_in(wheel_mm),
        dev_m=dev_m,
        kmh=dev_m * cadence * 60 / 1000,
    )


def cadence_for_speed(dev_m: float, kmh: float) -> float:
    """Cadence in rpm needed to hold a speed in km/h with a given development in metres."""
    return kmh * 1000 / (60 * dev_m)


def combos(dt: Drivetrain, cadence: float | None = None) -> list[Gear]:
    """Every chainring x cog combination, highest ratio first."""
    cad = dt.cadence if cadence is None else cadence
    gears = [make_gear(ring, cog, dt.wheel_mm, cad) for ring in dt.chainrings for cog in dt.cassette]
    return sorted(gears, key=lambda g: (-g.ratio, g.ring, g.cog))


def cross_chain(dt: Drivetrain) -> set:
    """The (ring, cog) pairs that cross the chain hard: biggest ring with smallest cog, and vice versa."""
    if len(set(dt.chainrings)) < 2 or len(set(dt.cassette)) < 2:
        return set()
    return {
        (max(dt.chainrings), min(dt.cassette)),
        (min(dt.chainrings), max(dt.cassette)),
    }


def steps(teeth) -> list:
    """Percent jump between each pair of neighbouring distinct tooth counts."""
    unique = sorted(set(teeth))
    return [(a, b, (b / a - 1) * 100) for a, b in zip(unique, unique[1:])]


def near_duplicates(dt: Drivetrain, tolerance: float | None = None) -> list:
    """Pairs of gears whose ratios differ by no more than `tolerance` percent."""
    tol = dt.tolerance if tolerance is None else tolerance
    gears = combos(dt)
    pairs = []
    for index, first in enumerate(gears):
        for second in gears[index + 1:]:
            diff = abs(first.ratio - second.ratio) / max(first.ratio, second.ratio) * 100
            if diff <= tol:
                pairs.append((first, second, diff))
    return pairs


def summarize(dt: Drivetrain, cadence: float | None = None) -> dict:
    gears = combos(dt, cadence)
    low = min(gears, key=lambda g: g.ratio)
    high = max(gears, key=lambda g: g.ratio)
    cog_steps = [pct for _, _, pct in steps(dt.cassette)]
    return {
        "low": low,
        "high": high,
        "range_ratio": high.ratio / low.ratio,
        "distinct": len({round(g.ratio, 3) for g in gears}),
        "total": len(gears),
        "max_step": max(cog_steps, default=0.0),
        "mean_step": sum(cog_steps) / len(cog_steps) if cog_steps else 0.0,
    }


def lint(dt: Drivetrain) -> list:
    """Non-fatal warnings about a drivetrain that parsed correctly."""
    warnings = []
    if len(set(dt.chainrings)) != len(dt.chainrings):
        warnings.append("repeated chainring tooth counts")
    if len(set(dt.cassette)) != len(dt.cassette):
        warnings.append("repeated cassette tooth counts")
    if len(dt.chainrings) > 3:
        warnings.append(f"{len(dt.chainrings)} chainrings is unusual (most drivetrains have 1-3)")
    if max(dt.chainrings) > 60:
        warnings.append(f"chainring of {max(dt.chainrings)}T is unusually large")
    if max(dt.cassette) > 50:
        warnings.append(f"cog of {max(dt.cassette)}T is unusually large")
    for ring, cog in sorted(cross_chain(dt), reverse=True):
        warnings.append(f"cross-chain combination {ring}x{cog} (avoid; wears the chain and drivetrain)")
    return warnings


# ---------------------------------------------------------------- output

def render(headers, rows):
    """Plain-text table: first and last columns left-aligned, the rest right-aligned."""
    widths = [max(len(str(cell)) for cell in column) for column in zip(headers, *rows)]
    lines = []
    for row in [headers, *rows]:
        cells = [str(cell) for cell in row]
        padded = [cells[0].ljust(widths[0])]
        padded += [cell.rjust(width) for cell, width in zip(cells[1:-1], widths[1:-1])]
        padded.append(cells[-1].ljust(widths[-1]))
        lines.append("  ".join(padded).rstrip())
    return "\n".join(lines)


# ---------------------------------------------------------------- commands

def cmd_check(args) -> int:
    dt = load(args.file)
    warnings = lint(dt)
    combinations = len(dt.chainrings) * len(dt.cassette)
    print(f"OK: {dt.name}: {len(dt.chainrings)} chainring(s), {len(dt.cassette)} cog(s), {combinations} combinations")
    for warning in warnings:
        print(f"warning: {warning}")
    return 1 if args.strict and warnings else 0


def cmd_table(args) -> int:
    dt = load(args.file)
    cadence = args.cadence or dt.cadence
    cross = cross_chain(dt)
    print(f"{dt.name}: wheel {dt.wheel_mm:g} mm ({wheel_diameter_in(dt.wheel_mm):.2f} in), {cadence:g} rpm")
    rows = []
    for gear in combos(dt, cadence):
        note = "cross-chain" if (gear.ring, gear.cog) in cross else ""
        rows.append([
            gear.ring, gear.cog, f"{gear.ratio:.2f}", f"{gear.inches:.1f}",
            f"{gear.dev_m:.2f}", f"{gear.kmh:.1f}", f"{gear.mph:.1f}", note,
        ])
    print(render(["Ring", "Cog", "Ratio", "Gear in", "Dev m", "km/h", "mph", "Note"], rows))
    return 0


def cmd_cadence(args) -> int:
    dt = load(args.file)
    rows = []
    for gear in combos(dt):
        rpm = cadence_for_speed(gear.dev_m, args.speed)
        if rpm > SPIN_LIMIT_RPM:
            note = "spinning fast"
        elif rpm < GRIND_LIMIT_RPM:
            note = "grinding"
        else:
            note = ""
        rows.append([gear.ring, gear.cog, f"{gear.inches:.1f}", f"{rpm:.1f}", note])
    print(f"{dt.name}: cadence needed for {args.speed:g} km/h")
    print(render(["Ring", "Cog", "Gear in", "rpm", "Note"], rows))
    return 0


def cmd_gaps(args) -> int:
    dt = load(args.file)
    limit = args.threshold or dt.gap
    print(f"{dt.name}: steps above {limit:g}% are flagged")
    for label, teeth in (("cassette", dt.cassette), ("chainrings", dt.chainrings)):
        print(f"{label}:")
        pairs = steps(teeth)
        if not pairs:
            print("  (only one tooth count, no steps)")
            continue
        for small, big, pct in pairs:
            flag = "  <- big gap" if pct > limit else ""
            print(f"  {small:>3}T -> {big:>3}T  {pct:5.1f}%{flag}")
    return 0


def cmd_duplicates(args) -> int:
    dt = load(args.file)
    tolerance = dt.tolerance if args.tolerance is None else args.tolerance
    pairs = near_duplicates(dt, tolerance)
    print(f"{dt.name}: gears whose ratios are within {tolerance:g}% of each other")
    if not pairs:
        print("no near-duplicate gears")
        return 0
    for first, second, diff in pairs:
        print(f"  {first.ring}x{first.cog} ({first.ratio:.3f}) ~ {second.ring}x{second.cog} ({second.ratio:.3f})  {diff:.2f}% apart")
    return 0


def cmd_range(args) -> int:
    dt = load(args.file)
    cadence = args.cadence or dt.cadence
    s = summarize(dt, cadence)
    low, high = s["low"], s["high"]
    print(f"{dt.name}: {s['total']} combinations at {cadence:g} rpm")
    print(f"lowest gear    {low.ring}x{low.cog}  ratio {low.ratio:.2f}  {low.inches:.1f} in  crawl {low.kmh:.1f} km/h")
    print(f"highest gear   {high.ring}x{high.cog}  ratio {high.ratio:.2f}  {high.inches:.1f} in  top {high.kmh:.1f} km/h")
    print(f"range ratio    {s['range_ratio']:.2f}")
    print(f"distinct gears {s['distinct']} of {s['total']}")
    print(f"cassette steps max {s['max_step']:.1f}%, mean {s['mean_step']:.1f}%")
    return 0


def cmd_compare(args) -> int:
    first = load(args.first)
    second = load(args.second)
    a, b = summarize(first), summarize(second)
    metrics = [
        ("lowest gear (in)", f"{a['low'].inches:.1f}", f"{b['low'].inches:.1f}"),
        ("highest gear (in)", f"{a['high'].inches:.1f}", f"{b['high'].inches:.1f}"),
        ("range ratio", f"{a['range_ratio']:.2f}", f"{b['range_ratio']:.2f}"),
        ("distinct gears", str(a["distinct"]), str(b["distinct"])),
        ("max cassette step", f"{a['max_step']:.1f}%", f"{b['max_step']:.1f}%"),
        ("mean cassette step", f"{a['mean_step']:.1f}%", f"{b['mean_step']:.1f}%"),
        ("top speed (km/h)", f"{a['high'].kmh:.1f}", f"{b['high'].kmh:.1f}"),
        ("crawl speed (km/h)", f"{a['low'].kmh:.1f}", f"{b['low'].kmh:.1f}"),
    ]
    print(render(["Metric", first.name, second.name], [list(row) for row in metrics]))
    return 0


def cmd_wheels(_args) -> int:
    rows = [[name, mm, f"{wheel_diameter_in(mm):.2f}"] for name, mm in WHEEL_PRESETS.items()]
    print(render(["Preset", "mm", "Dia in"], rows))
    print("Presets are approximate; measure your own wheel and write 'wheel: <n>mm'.")
    return 0


# ---------------------------------------------------------------- CLI

def positive(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive number, got {text}")
    return value


def nonnegative(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError(f"must be zero or more, got {text}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sprocket",
        description="Offline bicycle gearing calculator for plain-text drivetrain files.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    check = sub.add_parser("check", help="validate a drivetrain file and list warnings")
    check.add_argument("file")
    check.add_argument("--strict", action="store_true", help="exit 1 when there are warnings")
    check.set_defaults(func=cmd_check)

    table = sub.add_parser("table", help="every gear with ratio, gear inches, development and speed")
    table.add_argument("file")
    table.add_argument("--cadence", type=positive, help="override the file's cadence (rpm)")
    table.set_defaults(func=cmd_table)

    cad = sub.add_parser("cadence", help="cadence needed in each gear to hold a target speed")
    cad.add_argument("file")
    cad.add_argument("--speed", type=positive, required=True, help="target speed in km/h")
    cad.set_defaults(func=cmd_cadence)

    gaps = sub.add_parser("gaps", help="percent step between neighbouring cogs and chainrings")
    gaps.add_argument("file")
    gaps.add_argument("--threshold", type=positive, help="flag steps above this percent")
    gaps.set_defaults(func=cmd_gaps)

    dups = sub.add_parser("duplicates", help="gears whose ratios are nearly identical")
    dups.add_argument("file")
    dups.add_argument("--tolerance", type=nonnegative, help="ratio difference in percent")
    dups.set_defaults(func=cmd_duplicates)

    rng = sub.add_parser("range", help="gear range, crawl and top speed, distinct gear count")
    rng.add_argument("file")
    rng.add_argument("--cadence", type=positive, help="override the file's cadence (rpm)")
    rng.set_defaults(func=cmd_range)

    cmp_ = sub.add_parser("compare", help="side-by-side summary of two drivetrain files")
    cmp_.add_argument("first")
    cmp_.add_argument("second")
    cmp_.set_defaults(func=cmd_compare)

    wheels = sub.add_parser("wheels", help="list wheel size presets")
    wheels.set_defaults(func=cmd_wheels)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except GearError as exc:
        for line in exc.errors:
            print(f"error: {line}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc.strerror}: {exc.filename}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
