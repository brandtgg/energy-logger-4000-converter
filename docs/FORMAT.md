# Binary format and validation

This is an independent, deliberately limited implementation verified against one
private INFO/measurement pair. Offsets are zero-based. Integers are unsigned and
big endian; fields are binary integers, not BCD.

## Measurement stream

The stream mixes five-byte measurements and eight-byte timestamp markers:

| Bytes | Interpretation |
| --- | --- |
| Measurement 0–1 | Voltage integer / 10 V |
| Measurement 2–3 | Current integer / 1000 A |
| Measurement 4 | Power factor integer / 100 |
| Marker 0–2 | `E0 C5 EA` |
| Marker 3–7 | Month, day, year since 2000, hour, minute |
| End | `FF FF FF FF`, followed by optional FF padding |

Markers apply to the following sample; each complete slot occupies a nominal
minute. A timestamp is not stored in each measurement. A file may start with
measurements before any marker. Two plausible slots are required to accept a
headerless stream without a valid timestamp marker. This is not strong format
identification: unrelated bytes can pass the heuristic.

As synthetic examples, `08 FC 03 E8 50` gives 230.0 V, 1.000 A, PF 0.80,
230 VA and an active-power estimate of 184 W. `E0 C5 EA 01 0F 19 0C 00`
anchors the next sample to 2025-01-15 12:00 on the device clock.

The parser accepts voltage above 0 through 300 V, current through 20 A and PF
through 1. These are broad corruption guards, not specifications or calibration
limits. A zero current or PF is preserved as zero. Invalid complete slots export
blank measurements and raw bytes, and still occupy a minute. Values that look
plausible despite corruption cannot be detected reliably.

Recognizable fragments before a marker/end are skipped with warnings. A four-byte
fragment before FF padding is indistinguishable from a slot whose PF is FF; it is
retained as invalid with blank values. Missing end markers and short final records
produce warnings. Non-padding bytes after an end marker are warned about and
ignored. Insertions/deletions can destroy five-byte alignment; the next timestamp
marker restores alignment, but intermediate data may be unusable.

## INFO file

Expected size is 102 bytes. Detection uses `INFO:`, not file size or name alone.

| Offset | Length | Interpretation exported by this implementation |
| --- | --- | --- |
| 0 | 5 | ASCII `INFO:` |
| 5 | 3 | Total energy integer / 1000 kWh |
| 8 | 3 | Recorded-time counter, raw integer only |
| 11 | 3 | On-time counter, raw integer only |
| 84 | 1 | Unit ID (0–9) |
| 93 | 5 | Initial-setting hour, minute, month, day, year since 2000 |
| 98 | 4 | `FF FF FF FF` |

Other bytes include history and tariff fields; they are not exported. A partial
INFO file is usable if the signature and energy counter are complete. Unavailable
fields remain blank and structural problems produce warnings.

External format definitions label the two time counters as hundredths of hours.
That interpretation is inconsistent with this pair's nominal coverage and energy
history. Their raw values are preserved instead of reporting an unverified duration.
The initial-setting clock likewise need not be the start of the supplied data.

Automatic pairing only checks the immediately preceding hexadecimal filename
(case insensitive, pattern `[A-J][0-9A-F]{7}.BIN`) and its INFO signature. This
matches the supplied export; there is no verified universal session identifier.
Other naming schemes and subsequent data files need explicit `--info` selection.

## Private reference validation

Only aggregate results are published; no measurements or actual calendar dates
are included in this repository. The optional local regression test reads the
private files without adding them to Git.

| Check | Observed result |
| --- | --- |
| INFO size | 102 bytes |
| Measurement file size | 10,244 bytes |
| Complete measurements | 1,458; all pass the corruption guards |
| First timestamp marker | Byte 7,280, after 1,456 measurements |
| Measurements after marker | 2 |
| End marker / padding starts | Byte 7,298 |
| Nominal interval coverage | 1,458 minutes = 24 h 18 min |
| First-to-last timestamp span with backfill | 1,457 minutes = 24 h 17 min |
| Maximum reconstructed active power | 604.16048 W |
| INFO energy counter | 0.476 kWh |
| Sum of one-minute power estimates | 0.4474703195166667 kWh |
| INFO minus interval estimate | 0.0285296804833333 kWh (5.9936% of INFO) |

Default conversion assigns timestamps only to the final two rows. Optional
backfill assigns the preceding 1,456 timestamps by assuming uninterrupted logging.
Under that assumption the inferred start is 27 minutes later than the INFO
initial-setting clock. Neither continuous elapsed time nor a missing 27 minutes
of measurements can be established from this pair alone.

## Why the energy values differ

The estimate is `sum(voltage_V * current_A * power_factor) / 60000` kWh,
assigning one minute to each valid slot, including the last. Invalid slots and
missing fragments add no energy; the tool never integrates across timestamp gaps
or fills missing measurements. This sum is not a verified energy total.

The stored fields are quantized, and the product of separately averaged quantities
need not equal average active power. The device's independent accumulator may
also cover a different period or use finer internal samples. These are possible
explanations, not established firmware behavior.

Specific checks on this pair:

- 885 records store PF zero. The converter preserves it; assigning an arbitrary
  nonzero factor would invent measurements. A low-power reporting threshold is
  possible but cannot be established from the files.
- Assuming nearest-step rounding independently for voltage (±0.05 V), current
  (±0.0005 A), and PF (±0.005, clipped to 0–1), the products sum to a range of
  approximately 0.443280–0.453357 kWh. Even this upper bound is below 0.476 kWh.
  Simple rounding alone, under those assumptions, does not explain the gap.
- The 27-minute clock difference could indicate differing counter/log coverage.
  The gap corresponds to about 63.4 W over 27 minutes, but no such missing load
  is proved, reconstructed or inserted into the CSV.

No scale correction or calibration factor is applied. Resolving the discrepancy
requires controlled runs with known loads, counter resets and independently
measured elapsed time; these files alone are insufficient.

## Sources and scope

The field layout was cross-checked with the primary open-source implementations
[Peter Wu's Energy Logger definitions](https://github.com/Lekensteyn/el4000/blob/master/defs.py)
and [Valer Bocan's data reader](https://github.com/vbocan/Voltcraft-Data-Analyzer/blob/master/VoltcraftDataFile.py).
They link to Conrad's historical SD-card format v1.2 document, which was not
retrievable during this work. No external implementation code is vendored.
The byte counts, missing-prefix observations and energy comparisons above were
verified directly against the supplied pair. Other variants remain untested.
