# Sprocket

**An offline bicycle gearing calculator driven by one plain-text drivetrain file.**

Describe your wheels, chainrings and cassette in a few readable lines. Sprocket works out every gear's ratio, gear inches, development and speed, flags awkward steps and cross-chained combinations, and tells you which gears are almost identical.

No servers, no accounts, no network calls. Python 3 standard library only.

## Features

- **Plain-text drivetrain files** with comments, comma or space separated tooth counts, and case-insensitive keys
- **Line-numbered errors** that list every problem at once, such as unknown keys, bad tooth counts and duplicate keys
- **Lint warnings** for repeated teeth, oversized parts and cross-chain combinations, with `--strict` for CI
- **Full gear table** with ratio, gear inches, development in metres, and speed in km/h and mph at a chosen cadence
- **Cadence override** on the table and range commands to see speeds at a different pedalling rate
- **Cadence finder** that gives the rpm needed in every gear to hold a target speed, flagging grinding and spinning
- **Step analysis** that shows the percent jump between neighbouring cogs and chainrings, with big gaps flagged
- **Near-duplicate detection** that finds gears whose ratios are within a tolerance of each other
- **Range summary** with lowest and highest gear, range ratio, crawl and top speed, and distinct gear count
- **Drivetrain comparison** that puts two setups side by side on range, steps and speeds
- **Wheel presets** for common sizes, or any exact circumference in millimetres
- **Configurable thresholds** for the gap warning and duplicate tolerance, set per file or per command
- **Exit codes** that work in scripts: `0` success, `1` bad input, `2` usage error

## Quick start

Sprocket needs Python 3. There is nothing to install.

```bash
python3 sprocket.py check examples/commuter.txt
python3 sprocket.py table examples/commuter.txt
```

`examples/commuter.txt` describes a 700x28c commuter with two chainrings and an eight-speed cassette:

```text
# Commuter bike, 2x8 setup
name: Commuter
wheel: 700x28c
cadence: 85
chainrings: 48 34
cassette: 11 13 15 17 19 21 24 28
tolerance: 0.5
gap: 15
```

Other things to try:

```bash
python3 sprocket.py cadence examples/commuter.txt --speed 30
python3 sprocket.py gaps examples/commuter.txt --threshold 15
python3 sprocket.py range examples/gravel.txt --cadence 100
python3 sprocket.py compare examples/commuter.txt examples/gravel.txt
python3 sprocket.py check examples/broken.txt
```

### Drivetrain file format

| Key          | Required | Meaning                                                   |
|--------------|----------|-----------------------------------------------------------|
| `name`       | no       | Label shown in output (default `unnamed`)                 |
| `wheel`      | yes      | A preset such as `700x25c`, or a length such as `2105mm`  |
| `cadence`    | no       | Pedalling rate in rpm (default `90`)                      |
| `chainrings` | yes      | Tooth counts, separated by spaces or commas               |
| `cassette`   | yes      | Cog tooth counts, separated by spaces or commas           |
| `tolerance`  | no       | Ratio difference in percent to count as a duplicate (default `0.5`) |
| `gap`        | no       | Percent step between cogs to flag as a big gap (default `15`) |

Lines starting with `#` are comments. A trailing `# ...` also works.

## Commands

| Command                        | What it does                                              |
|--------------------------------|-----------------------------------------------------------|
| `check FILE [--strict]`        | Validate the file and print warnings                      |
| `table FILE [--cadence N]`     | Every gear, highest ratio first                           |
| `cadence FILE --speed KMH`     | Cadence needed in each gear for a target speed            |
| `gaps FILE [--threshold PCT]`  | Percent steps between neighbouring teeth                  |
| `duplicates FILE [--tolerance PCT]` | Gears with nearly identical ratios                   |
| `range FILE [--cadence N]`     | Lowest and highest gear, range ratio, crawl and top speed |
| `compare FILE_A FILE_B`        | Side-by-side summary of two drivetrains                   |
| `wheels`                       | List the wheel size presets                               |

Run `python3 sprocket.py --help` or `python3 sprocket.py <command> --help` for details.

## How it works

- **Ratio** is chainring teeth divided by cog teeth.
- **Gear inches** is the ratio multiplied by the wheel's diameter in inches. The diameter is worked out from the circumference.
- **Development** is the distance in metres covered per crank revolution: the ratio multiplied by the wheel circumference.
- **Speed** is development multiplied by cadence, converted to km/h. The mph figure divides km/h by 1.609344.
- **Cadence for speed** is the inverse of speed: target km/h divided by development, converted to rpm.
- **Step** between two neighbouring teeth counts is `(bigger / smaller - 1) × 100`.
- **Cross-chain** combinations are the largest chainring with the smallest cog, and the smallest chainring with the largest cog. These are only flagged when there are at least two chainrings and two cogs.

Wheel presets are approximate. For accurate figures, measure your own wheel and write its circumference as `wheel: <n>mm`.

## Running the tests

The tests use pytest. Install it if you do not have it, then run from the project root:

```bash
python3 -m pip install pytest
python3 -m pytest -q
```

The tests cover parsing and line-numbered errors, the gear maths, cross-chain and lint rules, duplicates, step analysis, and each CLI command.

## Project layout

```text
sprocket.py          the calculator and CLI (single module)
examples/            sample drivetrain files, including one with errors
tests/               pytest suite and conftest.py
```

