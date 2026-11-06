# energy-logger-4000-converter

Convert Voltcraft Energy Logger 4000 binary exports to CSV without Voltsoft.
Python 3.10+; standard library only. MIT licensed.

## Quick start — no Python experience needed

1. **Install Python.** Download it for your computer from
   [python.org](https://www.python.org/downloads/) and follow the installer.

2. **Download this tool.** Click **Code → Download ZIP** on this GitHub page,
   then extract the ZIP (Windows: right-click → **Extract All**).
   Open the extracted folder containing `convert.py`.

3. **Add your files.** Copy your measurement `.BIN` file and its INFO file into
   that same folder. They are not included in the download. The commands below
   use `A05FD3D6.BIN`; replace it with your measurement file's exact name.

4. **Open a command window in that folder.**

   **Windows:** In File Explorer, click the folder's address bar, type `cmd`,
   and press **Enter**.

   **macOS:** Press **⌘ Space**, type `Terminal`, and press **Enter**.
   Type `cd ` (including the space), drag the extracted folder from Finder into
   the Terminal window, then press **Enter**.

5. **Convert your file.** Copy the command for your computer into that window,
   replace the filename if needed, and press **Enter**.

   Windows:

   ```sh
   py convert.py A05FD3D6.BIN
   ```

   macOS:

   ```sh
   python3 convert.py A05FD3D6.BIN
   ```

   To set a known start time, add `--start-time "2025-01-15 08:30"` to the end
   of your command, replacing the example date and time. This replaces device
   times and assumes one uninterrupted minute per row. Otherwise, unknown times
   stay blank. Measurement values are never filled in.

6. **Open the result.** Find `A05FD3D6.csv` next to your BIN file and open it in
   Excel or LibreOffice. If all values appear in one column, import it as CSV
   with a comma separator and a period decimal separator. For another conversion,
   move or rename the existing CSV first; the tool never overwrites files.

More options and explanations follow below.

## Advanced usage

Examples below use `python3`; on Windows, use `py` instead.

### Installation

Clone or download this repository. No packages or installation step are needed.
Check your Python version with `python3 --version`.

### Usage

Open a terminal in the downloaded repository folder, or navigate there:

```sh
cd /path/to/energy-logger-4000-converter
mkdir -p data
```

Copy your measurement BIN files and associated INFO file into `data/`. Sample
files are not included. Replace the example filenames below with your own.
Each example is a separate command; run only the one you need.

**Basic conversion:**

```sh
python3 convert.py data/A05FD3D6.BIN
```

`python3` runs Python, `convert.py` is the converter, and `data/A05FD3D6.BIN`
is the measurement file to read. This creates `data/A05FD3D6.csv`.
Existing files are never overwritten; choose a new output name for another run.

| Option | What it does |
| --- | --- |
| `-o data/result.csv` | Choose the output path instead of the default `.csv` path. |
| `--info data/A05FD3D5.BIN` | Select the associated metadata file for comparing its stored energy counter with the interval estimate. It does not supply or correct measurement timestamps. |
| `--no-info` | Disable automatic metadata discovery and the INFO energy comparison. |
| `--help` | Show all options, including the timestamp options described below. |

**Choose metadata and output explicitly:**

```sh
python3 convert.py data/A05FD3D6.BIN --info data/A05FD3D5.BIN -o data/result.csv
```

Normally `--info` is optional: the converter checks the immediately preceding
filename for an `INFO:` signature. Measurement conversion also works without INFO.
Check that selected metadata belongs to the same export; matching device IDs alone
cannot establish this. Option names are case sensitive: use `--info`, not `--Info`.

**Export only the INFO metadata** (one summary row, no measurements):

```sh
python3 convert.py data/A05FD3D5.BIN -o data/info.csv
```

**Show command-line help:**

```sh
python3 convert.py --help
```

Diagnostics and an energy comparison go to stderr. Exit status is 0 for a usable
conversion (possibly with warnings), 1 for file/format errors, and 2 for CLI errors.

Open the resulting CSV in Excel or LibreOffice. If importing it, select a comma
as the column separator and a period as the decimal separator.

### CSV fields

| Column | Meaning |
| --- | --- |
| `record_index`, `byte_offset` | Zero-based slot index and source byte position |
| `timestamp` | Local device or user-supplied time in ISO 8601; blank when unknown; no timezone |
| `timestamp_source` | `marker`, `interval`, `backfilled`, `user_start`, or `missing` |
| `voltage_V`, `current_A` | Stored voltage (V) and current (A) |
| `power_factor` | Stored dimensionless factor, 0–1 |
| `active_power_estimate_W` | Reconstructed voltage × current × power factor (W) |
| `apparent_power_VA` | Voltage × current (VA) |
| `status`, `raw_hex` | `ok` or `invalid`, and original slot bytes for audit |

Invalid slots retain their position but have blank measurement fields. Incomplete
fragments are warned about. Measurement values are never interpolated or replaced.
INFO CSV contains energy (kWh), device ID, initial-setting clock and **raw** time
counters whose units remain unverified.

### Timestamps

Only timestamps are assigned; missing measurement values or rows are never created.
The INFO initial-setting clock is not used as a measurement start.

**Default:** A device timestamp marker dates the following row (`marker`). Later
slots advance by one minute (`interval`) until another marker resets the clock.
Rows before the first valid marker stay blank (`missing`).

**Backfill missing leading times:**

```sh
python3 convert.py data/A05FD3D6.BIN --backfill-timestamps -o data/with_timestamps.csv
```

This counts backward from the first valid marker at one minute per preceding row.
For example, three rows before a 10:03 marker become 10:00, 10:01 and 10:02.
These rows are labeled `backfilled`. This assumes continuous recording, needs a
valid marker and leaves damaged prefixes unfilled. Later device times are retained.

**Set a known start date and time:**

```sh
python3 convert.py data/A05FD3D6.BIN --start-time "2025-01-15 08:30" -o data/custom_times.csv
```

Replace the quoted example with the actual start of your first measurement row.
Use `YYYY-MM-DD HH:MM` or `YYYY-MM-DD HH:MM:SS`, without a timezone. Row 0 gets
that time, row 1 gets one minute later, and so on, including invalid complete slots.
All rows are labeled `user_start`. This **replaces all device timestamps**, including
later markers, and also works without any markers. It assumes no recording gaps;
it cannot recover pauses, missing intervals or daylight-saving changes. Use it only
when that assumption fits your recording. It cannot be combined with
`--backfill-timestamps`. Measurement values and energy estimates stay unchanged.

### Known limitations

Only the layout verified against the supplied Energy Logger 4000 pair is supported;
no claim is made for other models, firmware versions or device variants. Headerless
data detection is heuristic. Arbitrary byte corruption cannot always be identified
or repaired. Active power and interval energy are estimates from stored fields,
not the device's independent energy counter.

The private reference pair yields **1,458 records**, **24 h 18 min nominal interval
coverage**, **604.16048 W peak**, **0.476 kWh INFO energy**, and **0.447470320 kWh
interval energy**. The 6% discrepancy is unresolved; see
[binary format and validation notes](docs/FORMAT.md).

### Tests and private data

```sh
python3 -m unittest discover -v
# Optional regression check, only when the two private sample files are available:
ENERGY_LOGGER_PRIVATE_DATA=data python3 -m unittest discover -v
```

Public tests generate synthetic bytes. Private BIN files are not distributed.
All case variants of `.bin`, the `data/` directory and generated CSV files are
ignored by Git. Keep personal measurements there and do not force-add them.

## Disclaimer

This project is an independent, unofficial open-source tool and is not affiliated with, endorsed by, or supported by Voltcraft or its manufacturer.

Voltcraft and Voltsoft are trademarks of their respective owners.

The converter was independently developed to enable interoperability with measurement data generated by the Energy Logger 4000. It does not contain proprietary Voltsoft source code or software components.

The software is provided "as is", without warranty of any kind. Measurement data may be decoded incorrectly or incompletely. Users are responsible for verifying the accuracy and completeness of converted data before using it for technical, scientific, or commercial purposes.

This tool is not a replacement for certified measurement or evaluation software.
