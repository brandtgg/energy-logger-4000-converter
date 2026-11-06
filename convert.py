#!/usr/bin/env python3
"""Convert the tested Energy Logger 4000 BIN layout using only Python 3.10+."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import re
import sys

MAGIC = b"\xe0\xc5\xea"
MINUTE = timedelta(minutes=1)


class FormatError(ValueError):
    """The input cannot be identified as a supported logger export."""


@dataclass
class Info:
    total_energy_kwh: float
    unit_id: int | None = None
    initial_setting: datetime | None = None
    recorded_time_raw: int | None = None
    on_time_raw: int | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class Record:
    offset: int
    raw: bytes
    voltage: float | None
    current: float | None
    power_factor: float | None
    timestamp: datetime | None = None
    timestamp_source: str = "missing"

    @property
    def valid(self) -> bool:
        return self.voltage is not None

    @property
    def apparent_power(self) -> float | None:
        if not self.valid:
            return None
        return self.voltage * self.current

    @property
    def active_power(self) -> float | None:
        if not self.valid:
            return None
        return self.apparent_power * self.power_factor


@dataclass
class Measurements:
    records: list[Record]
    warnings: list[str]

    @property
    def energy_estimate_kwh(self) -> float:
        """Sum valid U*I*PF products, treating each as one minute; never fill gaps."""
        return sum(r.active_power for r in self.records if r.valid) / 60000


def parse_info(data: bytes) -> Info:
    if not data.startswith(b"INFO:") or len(data) < 8:
        raise FormatError("INFO file needs the INFO: signature and energy counter")
    info = Info(int.from_bytes(data[5:8], "big") / 1000)
    if len(data) != 102:
        info.warnings.append(f"INFO size is {len(data)} bytes; expected 102")
    if len(data) < 102 or data[98:102] != b"\xff" * 4:
        info.warnings.append("INFO end marker is missing or invalid")
    if len(data) >= 11:
        info.recorded_time_raw = int.from_bytes(data[8:11], "big")
    if len(data) >= 14:
        info.on_time_raw = int.from_bytes(data[11:14], "big")
    if len(data) >= 85:
        if data[84] <= 9:
            info.unit_id = data[84]
        else:
            info.warnings.append("invalid INFO unit ID")
    if len(data) >= 98:
        hour, minute, month, day, year = data[93:98]
        try:
            info.initial_setting = datetime(2000 + year, month, day, hour, minute)
        except ValueError:
            info.warnings.append("invalid INFO initial-setting date/time")
    return info


def _decode_record(raw: bytes, offset: int) -> Record:
    voltage = int.from_bytes(raw[:2], "big") / 10
    current = int.from_bytes(raw[2:4], "big") / 1000
    pf = raw[4] / 100
    # Broad corruption guards, not a device calibration or rated-range claim.
    if not (0 < voltage <= 300 and 0 <= current <= 20 and 0 <= pf <= 1):
        return Record(offset, raw, None, None, None)
    return Record(offset, raw, voltage, current, pf)


def parse_measurements(data: bytes, *, backfill_timestamps: bool = False) -> Measurements:
    """Read fixed-size slots; timestamp markers anchor the following slot."""
    if data.startswith((b"INFO:", b"\xb8\xad\xf2")):
        raise FormatError("expected measurements, received INFO or setup data")
    records: list[Record] = []
    warnings: list[str] = []
    offset = 0
    clock = None
    source = "missing"
    found_marker = False
    ended = False
    backfill_safe = True
    while offset < len(data):
        if data.startswith(b"\xff" * 4, offset):
            ended = True
            if any(value != 255 for value in data[offset:]):
                warnings.append(f"non-padding bytes after end marker at offset {offset}; ignored")
            break
        if data.startswith(MAGIC, offset):
            if len(data) - offset < 8:
                warnings.append(f"incomplete timestamp marker at offset {offset}; ignored")
                break
            month, day, year, hour, minute = data[offset + 3:offset + 8]
            try:
                new_clock = datetime(2000 + year, month, day, hour, minute)
            except ValueError:
                warnings.append(f"invalid timestamp marker at offset {offset}; clock cleared")
                clock = None
                backfill_safe = False
            else:
                if clock is not None and new_clock != clock:
                    warnings.append(f"timestamp discontinuity at offset {offset}; using new marker")
                if backfill_timestamps and not found_marker and records:
                    if backfill_safe and all(r.valid for r in records):
                        for index, record in enumerate(records):
                            record.timestamp = new_clock - (len(records) - index) * MINUTE
                            record.timestamp_source = "backfilled"
                        warnings.append(f"backfilled {len(records)} timestamps assuming continuous one-minute slots")
                    else:
                        warnings.append("leading timestamps not backfilled because the prefix is damaged")
                clock = new_clock
                source = "marker"
                found_marker = True
            offset += 8
            continue
        # A marker within a slot means a fragment, not a complete measurement.
        boundaries = []
        for code, limit in ((MAGIC, 5), (b"\xff" * 4, 4)):
            position = data.find(code, offset + 1, offset + limit + len(code) - 1)
            if offset < position < offset + limit:
                boundaries.append(position)
        # At byte 4, FF may be an invalid PF or padding after a four-byte
        # fragment. Preserve the slot as invalid rather than guessing.
        if boundaries:
            boundary = min(boundaries)
            warnings.append(f"incomplete record at offset {offset}; skipped {boundary - offset} bytes")
            backfill_safe = False
            clock = None
            offset = boundary
            continue
        if len(data) - offset < 5:
            warnings.append(f"incomplete trailing record at offset {offset}; ignored")
            break
        record = _decode_record(data[offset:offset + 5], offset)
        if not record.valid:
            warnings.append(f"invalid measurement at offset {offset}; exporting blank values")
        record.timestamp = clock
        record.timestamp_source = source if clock is not None else "missing"
        records.append(record)
        if clock is not None:
            clock += MINUTE
            source = "interval"
        offset += 5
    if not any(r.valid for r in records):
        raise FormatError("no plausible five-byte measurements found")
    # Headerless files have no definitive signature: require two plausible slots.
    if not found_marker and sum(r.valid for r in records) < 2:
        raise FormatError("headerless input needs at least two plausible measurement slots")
    if not found_marker:
        warnings.append("no valid timestamp marker; format identified heuristically")
    if not ended:
        warnings.append("measurement end marker missing; file may be incomplete")
    missing = sum(r.timestamp is None for r in records)
    if missing:
        warnings.append(f"{missing} records have no timestamp; CSV timestamps left blank")
    return Measurements(records, warnings)


def find_info(path: Path) -> Path | None:
    """Only consider the immediate predecessor filename, never arbitrary INFO files."""
    match = re.fullmatch(r"([A-J])([0-9A-F]{7})\.BIN", path.name.upper())
    if match is None or int(match[2], 16) == 0:
        return None
    expected = f"{match[1]}{int(match[2], 16) - 1:07X}.BIN"
    candidates = [p for p in path.parent.iterdir() if p.name.upper() == expected and p.is_file()]
    if len(candidates) == 1:
        with candidates[0].open("rb") as handle:
            if handle.read(5) == b"INFO:":
                return candidates[0]
    return None


def _number(value: float | None, places: int) -> str:
    return "" if value is None else f"{value:.{places}f}"


def write_measurements(path: Path, measurements: Measurements) -> None:
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["record_index", "byte_offset", "timestamp", "timestamp_source",
                         "voltage_V", "current_A", "power_factor",
                         "active_power_estimate_W", "apparent_power_VA", "status", "raw_hex"])
        for index, r in enumerate(measurements.records):
            writer.writerow([index, r.offset, r.timestamp.isoformat() if r.timestamp else "",
                             r.timestamp_source, _number(r.voltage, 1), _number(r.current, 3),
                             _number(r.power_factor, 2), _number(r.active_power, 5),
                             _number(r.apparent_power, 4), "ok" if r.valid else "invalid", r.raw.hex()])


def write_info(path: Path, info: Info) -> None:
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["total_energy_kWh", "unit_id", "initial_setting_timestamp",
                         "recorded_time_raw", "on_time_raw"])
        writer.writerow([f"{info.total_energy_kwh:.3f}", info.unit_id,
                         info.initial_setting.isoformat() if info.initial_setting else "",
                         info.recorded_time_raw, info.on_time_raw])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="measurement or INFO BIN file")
    parser.add_argument("-o", "--output", type=Path, help="new CSV file (default: input with .csv suffix)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--info", type=Path, help="associated INFO file; default: immediate predecessor filename")
    group.add_argument("--no-info", action="store_true", help="disable automatic INFO discovery")
    parser.add_argument("--backfill-timestamps", action="store_true",
                        help="infer leading timestamps from first marker assuming continuous minutes; labels inferred rows")
    args = parser.parse_args(argv)
    try:
        data = args.input.read_bytes()
        output = args.output or args.input.with_suffix(".csv")
        if data.startswith(b"INFO:"):
            if args.info or args.backfill_timestamps:
                raise FormatError("--info and --backfill-timestamps require measurement input")
            info = parse_info(data)
            for warning in info.warnings:
                print(f"warning: {warning}", file=sys.stderr)
            write_info(output, info)
            print(f"Wrote INFO CSV: {output}", file=sys.stderr)
            return 0
        measurements = parse_measurements(data, backfill_timestamps=args.backfill_timestamps)
        info = None
        info_path = args.info
        if info_path is None and not args.no_info:
            try:
                info_path = find_info(args.input)
            except OSError as exc:
                measurements.warnings.append(f"automatic INFO discovery failed: {exc}")
        if info_path is not None:
            try:
                info = parse_info(info_path.read_bytes())
                match = re.fullmatch(r"([A-J])[0-9A-F]{7}\.BIN", args.input.name.upper())
                if match and info.unit_id is not None and ord(match[1]) - ord("A") != info.unit_id:
                    raise FormatError("INFO unit ID does not match measurement filename")
            except (OSError, FormatError) as exc:
                if args.info:
                    raise
                measurements.warnings.append(f"automatic INFO ignored: {exc}")
                info = None
        for warning in measurements.warnings + (info.warnings if info else []):
            print(f"warning: {warning}", file=sys.stderr)
        write_measurements(output, measurements)
        valid = [r for r in measurements.records if r.valid]
        count = len(valid)
        print(f"Wrote {len(measurements.records)} rows ({count} valid) to {output}", file=sys.stderr)
        print(f"Nominal coverage: {count} one-minute intervals = {count / 60:.3f} h (not verified elapsed time)", file=sys.stderr)
        print(f"Maximum active power estimate: {max(r.active_power for r in valid):.5f} W", file=sys.stderr)
        estimate = measurements.energy_estimate_kwh
        print(f"Interval energy estimate: {estimate:.9f} kWh (valid slots only)", file=sys.stderr)
        if info:
            print(f"INFO energy counter: {info.total_energy_kwh:.3f} kWh ({info_path})", file=sys.stderr)
            print(f"INFO minus interval estimate: {info.total_energy_kwh - estimate:+.9f} kWh; scopes may differ", file=sys.stderr)
        return 0
    except (OSError, FormatError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
