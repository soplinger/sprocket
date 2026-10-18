import math
from pathlib import Path

import pytest

import sprocket
from sprocket import GearError, Drivetrain

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

VALID = """\
name: Test
wheel: 2000mm
cadence: 60
chainrings: 40 30
cassette: 10 20
"""


def make_dt(**overrides):
    base = dict(
        name="T", wheel_mm=2000.0, cadence=60.0,
        chainrings=[40, 30], cassette=[10, 20], tolerance=0.5, gap=15.0,
    )
    base.update(overrides)
    return Drivetrain(**base)


def parse_errors(text):
    with pytest.raises(GearError) as info:
        sprocket.parse(text)
    return info.value.errors


# ---------------------------------------------------------------- parsing

def test_parse_valid_file_applies_defaults():
    dt = sprocket.parse("wheel: 700x25c\nchainrings: 48\ncassette: 11 12\n")
    assert dt.name == "unnamed"
    assert dt.wheel_mm == 2105
    assert dt.cadence == 90
    assert dt.tolerance == 0.5
    assert dt.gap == 15
    assert dt.chainrings == [48]
    assert dt.cassette == [11, 12]


def test_parse_accepts_commas_extra_spaces_and_comments():
    text = "  Wheel :  2105MM   # measured\n\nchainrings:48,  34\ncassette:  11 ,13\t15\n"
    dt = sprocket.parse(text)
    assert dt.wheel_mm == 2105
    assert dt.chainrings == [48, 34]
    assert dt.cassette == [11, 13, 15]


def test_unknown_key_reports_its_line():
    errors = parse_errors("wheel: 700x25c\nspeed: 90\nchainrings: 48\ncassette: 11\n")
    assert errors == ["line 2: unknown key 'speed'"]


def test_glued_tooth_count_reports_token_and_line():
    errors = parse_errors("wheel: 700x25c\nchainrings: 48t 34\ncassette: 11\n")
    assert errors == ["line 2: '48t' is not a tooth count in chainrings"]


def test_duplicate_key_points_at_first_occurrence():
    errors = parse_errors("wheel: 700x25c\nchainrings: 48\nchainrings: 52\ncassette: 11\n")
    assert errors == ["line 3: duplicate key 'chainrings' (first on line 2)"]


def test_missing_colon_and_missing_required_keys_are_all_reported():
    errors = parse_errors("wheel 700x25c\n")
    assert "line 1: expected 'key: value', got 'wheel 700x25c'" in errors
    assert "missing required key 'chainrings'" in errors
    assert "missing required key 'cassette'" in errors


def test_bad_wheel_and_out_of_range_values_are_collected():
    errors = parse_errors("wheel: 700x99c\ncadence: 900\nchainrings: 48\ncassette: 11 0\n")
    assert any(e.startswith("line 1: unknown wheel '700x99c'") for e in errors)
    assert any(e.startswith("line 2: cadence must be between") for e in errors)
    assert any(e.startswith("line 4: 0 teeth is out of range") for e in errors)


def test_broken_example_file_reports_every_problem():
    with pytest.raises(GearError) as info:
        sprocket.load(str(EXAMPLES / "broken.txt"))
    errors = info.value.errors
    assert len(errors) == 5
    assert errors[0].startswith("line 3: unknown wheel")
    assert errors[1] == "line 4: '48t' is not a tooth count in chainrings"
    assert errors[2] == "line 5: 'xx' is not a tooth count in cassette"
    assert errors[3] == "line 6: unknown key 'speed'"
    assert errors[4] == "line 7: duplicate key 'chainrings' (first on line 4)"


# ---------------------------------------------------------------- maths

def test_wheel_diameter_matches_circumference():
    assert sprocket.wheel_diameter_in(2000) == pytest.approx(2000 / math.pi / 25.4)


def test_single_gear_ratio_gear_inches_and_development():
    gear = sprocket.make_gear(48, 12, 2000, 60)
    assert gear.ratio == pytest.approx(4.0)
    assert gear.dev_m == pytest.approx(8.0)
    assert gear.inches == pytest.approx(4.0 * sprocket.wheel_diameter_in(2000))


def test_speed_formula_is_development_times_cadence():
    # 1 m development at 60 rpm is 60 m per minute, which is 3.6 km/h.
    gear = sprocket.make_gear(10, 10, 1000, 60)
    assert gear.kmh == pytest.approx(3.6)
    assert gear.mph == pytest.approx(3.6 / sprocket.KM_PER_MILE)


def test_cadence_for_speed_inverts_speed():
    gear = sprocket.make_gear(40, 16, 2105, 90)
    rpm = sprocket.cadence_for_speed(gear.dev_m, 30)
    back = sprocket.make_gear(40, 16, 2105, rpm)
    assert back.kmh == pytest.approx(30)


def test_combos_are_sorted_highest_ratio_first():
    gears = sprocket.combos(make_dt())
    ratios = [g.ratio for g in gears]
    assert ratios == sorted(ratios, reverse=True)
    assert len(gears) == 4
    assert (gears[0].ring, gears[0].cog) == (40, 10)


def test_cross_chain_needs_two_rings_and_two_cogs():
    assert sprocket.cross_chain(make_dt()) == {(40, 10), (30, 20)}
    assert sprocket.cross_chain(make_dt(chainrings=[40])) == set()
    assert sprocket.cross_chain(make_dt(cassette=[12])) == set()


def test_steps_are_percent_jumps_between_distinct_teeth():
    result = sprocket.steps([11, 13, 13, 15])
    assert [(a, b) for a, b, _ in result] == [(11, 13), (13, 15)]
    assert result[0][2] == pytest.approx((13 / 11 - 1) * 100)


def test_near_duplicates_finds_equal_ratios():
    dt = make_dt(chainrings=[48, 36], cassette=[12, 9], tolerance=0.1)
    pairs = sprocket.near_duplicates(dt)
    names = {frozenset({(a.ring, a.cog), (b.ring, b.cog)}) for a, b, _ in pairs}
    assert frozenset({(48, 12), (36, 9)}) in names


def test_summarize_reports_range_and_steps():
    s = sprocket.summarize(make_dt())
    assert s["low"].ratio == pytest.approx(30 / 20)
    assert s["high"].ratio == pytest.approx(40 / 10)
    assert s["range_ratio"] == pytest.approx(4 / 1.5)
    assert s["total"] == 4
    assert s["distinct"] == 4
    assert s["max_step"] == pytest.approx(100.0)


def test_lint_warns_about_repeats_and_cross_chaining():
    dt = make_dt(chainrings=[40, 40], cassette=[10, 20])
    warnings = sprocket.lint(dt)
    assert "repeated chainring tooth counts" in warnings
    assert any("cross-chain" in w for w in sprocket.lint(make_dt()))


# ---------------------------------------------------------------- CLI

def test_check_example_is_clean_and_strict_fails_on_cross_chain(capsys):
    commuter = str(EXAMPLES / "commuter.txt")
    assert sprocket.main(["check", commuter]) == 0
    assert "warning: cross-chain" in capsys.readouterr().out
    assert sprocket.main(["check", commuter, "--strict"]) == 1


def test_table_prints_every_combination(capsys):
    assert sprocket.main(["table", str(EXAMPLES / "commuter.txt")]) == 0
    out = capsys.readouterr().out
    assert "Commuter" in out
    assert "cross-chain" in out
    assert out.count("\n") >= 2 + 16


def test_cli_reports_bad_file_on_stderr_and_returns_1(capsys):
    assert sprocket.main(["table", str(EXAMPLES / "broken.txt")]) == 1
    err = capsys.readouterr().err
    assert "line 4" in err and "line 5" in err


def test_cli_reports_missing_file(capsys):
    assert sprocket.main(["range", "no-such-file.txt"]) == 1
    assert "No such file" in capsys.readouterr().err


def test_cadence_command_flags_extremes(tmp_path, capsys):
    path = tmp_path / "bike.txt"
    path.write_text("wheel: 2000mm\nchainrings: 50\ncassette: 11 30\n")
    assert sprocket.main(["cadence", str(path), "--speed", "25"]) == 0
    out = capsys.readouterr().out
    assert "grinding" in out or "spinning fast" in out


def test_gaps_flags_big_steps(capsys):
    assert sprocket.main(["gaps", str(EXAMPLES / "commuter.txt"), "--threshold", "15"]) == 0
    out = capsys.readouterr().out
    assert "11T ->  13T" in out
    assert "big gap" in out


def test_duplicates_command_and_compare_and_range(capsys):
    assert sprocket.main(["duplicates", str(EXAMPLES / "gravel.txt")]) == 0
    assert sprocket.main(["compare", str(EXAMPLES / "commuter.txt"), str(EXAMPLES / "gravel.txt")]) == 0
    assert sprocket.main(["range", str(EXAMPLES / "gravel.txt"), "--cadence", "100"]) == 0
    out = capsys.readouterr().out
    assert "range ratio" in out
    assert "Gravel" in out


def test_wheels_lists_presets(capsys):
    assert sprocket.main(["wheels"]) == 0
    assert "700x25c" in capsys.readouterr().out
