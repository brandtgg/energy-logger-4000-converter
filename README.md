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

   To set a known start time, add `--start-time "2026-10-15 08:30"` to the end
   of your command, replacing the example date and time. This replaces device
   times and assumes one uninterrupted minute per row. Otherwise, unknown times
   stay blank. Measurement values are never filled in.

6. **Open the result.** Find `A05FD3D6.csv` next to your BIN file and open it in
   Excel or LibreOffice. If all values appear in one column, import it as CSV
   with a comma separator and a period decimal separator. For another conversion,
   move or rename the existing CSV first; the tool never overwrites files.

More options and explanations follow below.

## Advanced usage

Use `python3` on macOS/Linux or `py` on Windows. No extra packages are required.

| Option | Purpose |
| --- | --- |
| `-o result.csv` | Choose a new output filename; existing files are never overwritten. |
| `--info FILE` | Read associated metadata for the energy comparison; does not set timestamps. |
| `--no-info` | Skip automatic metadata discovery. |
| `--backfill-timestamps` | Infer leading times backward from the first valid device marker, one minute per row. |
| `--start-time "YYYY-MM-DD HH:MM"` | Set the first row's time and replace all device times with a continuous one-minute timeline. |
| `--help` | Show all command-line options. |

For example, select metadata and an output file explicitly:

```sh
python3 convert.py A05FD3D6.BIN --info A05FD3D5.BIN -o result.csv
```

INFO is optional and normally detected by the immediately preceding filename.
Use metadata from the same export. Passing an INFO file as the input instead
exports one metadata row, without measurements.

### Timestamps

By default, device markers date the following row; subsequent rows advance by
one minute until another marker. Unknown leading times stay blank.

- `--backfill-timestamps` needs a valid marker and an undamaged prefix. Three rows
  before a 10:03 marker become 10:00, 10:01 and 10:02; later device times remain.
- `--start-time` works without markers and overrides all device times. Include the
  date, keep the quotes, and optionally add seconds (`YYYY-MM-DD HH:MM:SS`).

```sh
python3 convert.py A05FD3D6.BIN --start-time "2025-01-15 08:30" -o custom_times.csv
```

Both options assume continuous one-minute slots, including invalid complete slots;
recording gaps cannot be recovered. They cannot be combined. No missing measurement
values or rows are created. The INFO initial-setting clock is not a recording start.

### CSV output

| Fields | Meaning |
| --- | --- |
| `timestamp`, `timestamp_source` | Local time without a timezone; origin: `marker`, `interval`, `backfilled`, `user_start`, or `missing`. |
| `voltage_V`, `current_A`, `power_factor` | Decoded voltage (V), current (A), and dimensionless power factor. |
| `active_power_estimate_W`, `apparent_power_VA` | Reconstructed U × I × PF (W) and U × I (VA). |
| `record_index`, `byte_offset`, `status`, `raw_hex` | Source position, validity and original slot bytes for checking results. |

Invalid slots have blank measurement fields; damaged or incomplete input produces
warnings. INFO output contains energy (kWh), device ID, initial-setting time and
unverified raw time counters. Diagnostics go to stderr; exit codes are 0 for a
usable conversion (possibly with warnings), 1 for file/format errors, and 2 for CLI errors.

### Limitations and validation

Only the supplied Energy Logger 4000 layout has been tested. Headerless detection
is heuristic, and some corruption may go undetected. Power and interval energy are
estimates. The private reference pair yields 1,458 records (24 h 18 min nominal
coverage), 604.16048 W peak and 0.447470320 kWh versus 0.476 kWh in INFO. The roughly
6% energy difference remains unresolved. See [format and validation notes](docs/FORMAT.md).

### Tests and private data

```sh
python3 -m unittest discover -v
# Optional: check the private reference pair stored in data/
ENERGY_LOGGER_PRIVATE_DATA=data python3 -m unittest discover -v
```

Public tests use synthetic data. BIN files, generated CSVs and `data/` are ignored
by Git. Private measurement files are not included; do not force-add them.

## Disclaimer

This project is an independent, unofficial open-source tool and is not affiliated with, endorsed by, or supported by Voltcraft or its manufacturer.

Voltcraft and Voltsoft are trademarks of their respective owners.

The converter was independently developed to enable interoperability with measurement data generated by the Energy Logger 4000. It does not contain proprietary Voltsoft source code or software components.

The software is provided "as is", without warranty of any kind. Measurement data may be decoded incorrectly or incompletely. Users are responsible for verifying the accuracy and completeness of converted data before using it for technical, scientific, or commercial purposes.

This tool is not a replacement for certified measurement or evaluation software.
