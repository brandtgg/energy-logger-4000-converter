"""Public fixtures are generated here, never copied from private measurements."""

import contextlib
import csv
from datetime import datetime, timedelta, timezone
import io
import os
from pathlib import Path
import struct
import tempfile
import unittest

import convert

END = b"\xff" * 4


def sample(voltage=2300, current=1000, pf=80):
    return struct.pack(">HHB", voltage, current, pf)


def marker(month=1, day=15, year=25, hour=12, minute=0):
    return convert.MAGIC + bytes([month, day, year, hour, minute])


def metadata():
    data = bytearray(102)
    data[:5] = b"INFO:"
    data[5:8] = (321).to_bytes(3, "big")
    data[8:11] = (123456).to_bytes(3, "big")
    data[11:14] = (65432).to_bytes(3, "big")
    data[93:98] = bytes([11, 30, 1, 15, 25])
    data[98:] = END
    return bytes(data)


class DecoderTests(unittest.TestCase):
    def test_big_endian_scaling_and_derived_power(self):
        result = convert.parse_measurements(marker() + sample() + END)
        row = result.records[0]
        self.assertEqual((row.voltage, row.current, row.power_factor), (230, 1, .8))
        self.assertAlmostEqual(row.apparent_power, 230)
        self.assertAlmostEqual(row.active_power, 184)
        self.assertAlmostEqual(result.energy_estimate_kwh, 184 / 60000)
        self.assertEqual(row.timestamp, datetime(2025, 1, 15, 12))
        self.assertEqual(row.timestamp_source, "marker")
        self.assertFalse(result.warnings)

    def test_large_current_not_artificially_rejected(self):
        row = convert.parse_measurements(marker() + sample(current=12345) + END).records[0]
        self.assertEqual(row.current, 12.345)

    def test_zero_pf_and_current_are_values(self):
        result = convert.parse_measurements(marker() + sample(pf=0) + sample(current=0) + END)
        self.assertTrue(all(r.valid for r in result.records))
        self.assertEqual([r.active_power for r in result.records], [0, 0])

    def test_rollover_and_discontinuous_markers(self):
        data = (marker(month=12, day=31, hour=23, minute=59) + sample() * 2
                + marker(year=26, month=1, day=1, hour=1) + sample() + END)
        result = convert.parse_measurements(data)
        self.assertEqual(result.records[1].timestamp, datetime(2026, 1, 1))
        self.assertEqual(result.records[2].timestamp, datetime(2026, 1, 1, 1))
        self.assertTrue(any("discontinuity" in w for w in result.warnings))

    def test_missing_timestamps_remain_blank_by_default(self):
        result = convert.parse_measurements(sample() * 2 + marker() + sample() + END)
        self.assertEqual([r.timestamp for r in result.records[:2]], [None, None])
        self.assertEqual(result.records[2].timestamp_source, "marker")

    def test_backfill_is_explicit_and_labeled(self):
        result = convert.parse_measurements(sample() * 2 + marker() + sample() + END,
                                            backfill_timestamps=True)
        self.assertEqual(result.records[0].timestamp, datetime(2025, 1, 15, 11, 58))
        self.assertEqual(result.records[0].timestamp_source, "backfilled")
        self.assertTrue(any("assuming" in w for w in result.warnings))

    def test_headerless_data_has_no_invented_date(self):
        result = convert.parse_measurements(sample() * 2 + END, backfill_timestamps=True)
        self.assertTrue(all(r.timestamp is None for r in result.records))
        self.assertTrue(any("heuristically" in w for w in result.warnings))

    def test_start_time_replaces_device_clock_and_preserves_measurements(self):
        data = sample() + marker() + sample() + marker(hour=15) + sample() + END
        original = convert.parse_measurements(data)
        start = datetime(2026, 2, 28, 23, 59, 30)
        result = convert.parse_measurements(data, start_time=start)
        self.assertEqual([r.timestamp for r in result.records],
                         [start + index * timedelta(minutes=1) for index in range(3)])
        self.assertTrue(all(r.timestamp_source == "user_start" for r in result.records))
        self.assertEqual([r.raw for r in result.records], [r.raw for r in original.records])
        self.assertEqual([r.active_power for r in result.records], [r.active_power for r in original.records])
        self.assertEqual(result.energy_estimate_kwh, original.energy_estimate_kwh)
        self.assertTrue(any("replaces all device timestamps" in w for w in result.warnings))
        self.assertFalse(any("left blank" in w or "using new marker" in w for w in result.warnings))

    def test_start_time_without_markers_counts_invalid_slots(self):
        data = sample() + sample(pf=101) + sample() + END
        start = datetime(2025, 1, 1)
        result = convert.parse_measurements(data, start_time=start)
        self.assertFalse(result.records[1].valid)
        self.assertIsNone(result.records[1].active_power)
        self.assertEqual(result.records[2].timestamp, start + timedelta(minutes=2))

    def test_start_time_rejects_ambiguous_settings_and_overflow(self):
        for kwargs in ({"start_time": datetime(2025, 1, 1), "backfill_timestamps": True},
                       {"start_time": datetime(2025, 1, 1, tzinfo=timezone.utc)},
                       {"start_time": datetime(9999, 12, 31, 23, 59)}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(convert.FormatError):
                    convert.parse_measurements(sample() * 2 + END, **kwargs)

    def test_invalid_slot_is_blank_and_preserves_minute(self):
        data = marker() + sample() + sample(pf=101) + sample() + END
        result = convert.parse_measurements(data)
        self.assertEqual(len(result.records), 3)
        self.assertIsNone(result.records[1].active_power)
        self.assertEqual(result.records[2].timestamp, datetime(2025, 1, 15, 12, 2))
        self.assertAlmostEqual(result.energy_estimate_kwh, 368 / 60000)
        self.assertTrue(any("invalid measurement" in w for w in result.warnings))

    def test_invalid_date_clears_clock_until_new_marker(self):
        result = convert.parse_measurements(marker() + sample() + marker(month=13)
                                            + sample() + marker(hour=13) + sample() + END)
        self.assertIsNone(result.records[1].timestamp)
        self.assertEqual(result.records[2].timestamp, datetime(2025, 1, 15, 13))

    def test_damaged_prefix_not_backfilled(self):
        result = convert.parse_measurements(sample() + sample(pf=101) + marker() + sample() + END,
                                            backfill_timestamps=True)
        self.assertIsNone(result.records[0].timestamp)

    def test_partial_records_before_marker_are_not_measurements(self):
        for size in range(1, 5):
            with self.subTest(size=size):
                result = convert.parse_measurements(marker() + sample() + sample()[:size]
                                                    + marker(hour=13) + sample() + END)
                self.assertEqual(len(result.records), 2)
                self.assertTrue(any("incomplete record" in w for w in result.warnings))

    def test_truncation_preserves_complete_records(self):
        for tail in (b"", sample()[:1], sample()[:4], convert.MAGIC + b"\x01"):
            with self.subTest(tail=tail):
                result = convert.parse_measurements(marker() + sample() + tail)
                self.assertEqual(len(result.records), 1)
                self.assertTrue(any("end marker missing" in w for w in result.warnings))

    def test_partial_record_before_end_marker(self):
        for size in range(1, 4):
            with self.subTest(size=size):
                result = convert.parse_measurements(marker() + sample() + sample()[:size] + END * 10)
                self.assertEqual(len(result.records), 1)
                self.assertTrue(any("incomplete record" in w for w in result.warnings))

    def test_four_byte_fragment_before_padding_is_ambiguous_invalid_slot(self):
        result = convert.parse_measurements(marker() + sample() + sample()[:4] + END * 10)
        self.assertEqual(len(result.records), 2)
        self.assertFalse(result.records[1].valid)

    def test_padding_and_nonpadding_trailer(self):
        clean = convert.parse_measurements(marker() + sample() + END * 100)
        self.assertEqual(len(clean.records), 1)
        dirty = convert.parse_measurements(marker() + sample() + END + b"junk")
        self.assertTrue(any("non-padding" in w for w in dirty.warnings))

    def test_reject_unrecognized_or_empty_input(self):
        for data in (b"", b"hello world", END * 5, metadata(), b"\xb8\xad\xf2" + b"\0" * 17,
                     sample() + END, marker() + sample(pf=255) + END):
            with self.subTest(data=data[:8]):
                with self.assertRaises(convert.FormatError):
                    convert.parse_measurements(data)

    def test_info_signature_and_independent_fields(self):
        result = convert.parse_info(metadata())
        self.assertEqual(result.total_energy_kwh, .321)
        self.assertEqual(result.initial_setting, datetime(2025, 1, 15, 11, 30))
        self.assertEqual(result.recorded_time_raw, 123456)
        self.assertEqual(result.on_time_raw, 65432)
        self.assertEqual(result.unit_id, 0)
        self.assertFalse(result.warnings)

    def test_partial_info_never_pads_missing_fields(self):
        result = convert.parse_info(metadata()[:8])
        self.assertEqual(result.total_energy_kwh, .321)
        self.assertIsNone(result.initial_setting)
        self.assertIsNone(result.recorded_time_raw)
        self.assertTrue(result.warnings)
        with self.assertRaises(convert.FormatError):
            convert.parse_info(b"INFO:\0")

    def test_invalid_info_clock_and_id(self):
        data = bytearray(metadata())
        data[84] = 255
        data[95] = 0
        result = convert.parse_info(bytes(data))
        self.assertIsNone(result.unit_id)
        self.assertIsNone(result.initial_setting)
        self.assertEqual(len(result.warnings), 2)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / "A0000021.BIN"
        self.input.write_bytes(sample() * 2 + marker() + sample() + END)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = convert.main([str(arg) for arg in args])
        return status, out.getvalue(), err.getvalue()

    def read_csv(self, name):
        with (self.root / name).open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def test_auto_info_and_default_output(self):
        (self.root / "a0000020.bin").write_bytes(metadata())
        status, _, err = self.run_cli(self.input)
        self.assertEqual(status, 0, err)
        self.assertIn("0.321 kWh", err)
        rows = self.read_csv("A0000021.csv")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["timestamp"], "")
        self.assertEqual(rows[0]["active_power_estimate_W"], "184.00000")
        self.assertEqual(rows[2]["timestamp_source"], "marker")

    def test_explicit_info_output_and_backfill(self):
        info = self.root / "summary.BIN"
        info.write_bytes(metadata())
        status, _, err = self.run_cli(self.input, "--info", info, "-o", self.root / "result.csv",
                                     "--backfill-timestamps")
        self.assertEqual(status, 0, err)
        self.assertEqual(self.read_csv("result.csv")[0]["timestamp_source"], "backfilled")

    def test_info_only_csv(self):
        self.input.write_bytes(metadata())
        status, _, err = self.run_cli(self.input)
        self.assertEqual(status, 0, err)
        self.assertEqual(self.read_csv("A0000021.csv")[0]["total_energy_kWh"], "0.321")

    def test_start_time_cli_writes_user_timeline(self):
        status, _, err = self.run_cli(self.input, "--start-time", "2025-04-05 08:30:15")
        self.assertEqual(status, 0, err)
        rows = self.read_csv("A0000021.csv")
        self.assertEqual(rows[0]["timestamp"], "2025-04-05T08:30:15")
        self.assertEqual(rows[-1]["timestamp"], "2025-04-05T08:32:15")
        self.assertTrue(all(row["timestamp_source"] == "user_start" for row in rows))

    def test_start_time_cli_rejects_invalid_dates_and_conflicting_options(self):
        cases = [["--start-time", value] for value in
                 ("08:30", "2025-01-01", "2025-02-30 08:30", "2025-01-01 24:00",
                  "2025-01-01T08:30Z", "2025-01-01T08:30+01:00")]
        cases.append(["--start-time", "2025-01-01 08:30", "--backfill-timestamps"])
        for args in cases:
            with self.subTest(args=args):
                with self.assertRaises(SystemExit) as caught:
                    self.run_cli(self.input, *args)
                self.assertEqual(caught.exception.code, 2)
                self.assertFalse((self.root / "A0000021.csv").exists())
        self.assertEqual(convert._parse_start_time("2025-01-01T08:30"), datetime(2025, 1, 1, 8, 30))

    def test_start_time_rejects_info_input(self):
        self.input.write_bytes(metadata())
        status, _, err = self.run_cli(self.input, "--start-time", "2025-01-01 08:30")
        self.assertEqual(status, 1)
        self.assertIn("require measurement input", err)
        self.assertFalse((self.root / "A0000021.csv").exists())

    def test_no_info_and_unrelated_info_not_used(self):
        (self.root / "other.BIN").write_bytes(metadata())
        status, _, err = self.run_cli(self.input, "--no-info")
        self.assertEqual(status, 0, err)
        self.assertNotIn("INFO energy", err)
        self.assertIsNone(convert.find_info(self.input))

    def test_existing_output_and_input_never_overwritten(self):
        original = self.input.read_bytes()
        status, _, _ = self.run_cli(self.input, "-o", self.input)
        self.assertEqual(status, 1)
        self.assertEqual(self.input.read_bytes(), original)
        target = self.root / "existing.csv"
        target.write_text("keep me")
        status, _, _ = self.run_cli(self.input, "-o", target)
        self.assertEqual(status, 1)
        self.assertEqual(target.read_text(), "keep me")

    def test_missing_or_invalid_explicit_info_does_not_write(self):
        for name in ("absent.BIN", self.input.name):
            status, _, err = self.run_cli(self.input, "--info", self.root / name)
            self.assertEqual(status, 1, err)
            self.assertFalse((self.root / "A0000021.csv").exists())

    def test_mismatched_info_id(self):
        data = bytearray(metadata())
        data[84] = 1
        info = self.root / "summary.BIN"
        info.write_bytes(data)
        status, _, err = self.run_cli(self.input, "--info", info)
        self.assertEqual(status, 1)
        self.assertIn("unit ID", err)

    def test_invalid_record_csv_has_blank_measurements(self):
        self.input.write_bytes(marker() + sample() + sample(pf=255) + END)
        status, _, err = self.run_cli(self.input)
        self.assertEqual(status, 0, err)
        row = self.read_csv("A0000021.csv")[1]
        self.assertEqual(row["status"], "invalid")
        self.assertEqual(row["voltage_V"], "")
        self.assertEqual(row["active_power_estimate_W"], "")
        self.assertEqual(row["raw_hex"], sample(pf=255).hex())

    def test_help(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_cli("--help")
        self.assertEqual(caught.exception.code, 0)


@unittest.skipUnless(os.environ.get("ENERGY_LOGGER_PRIVATE_DATA"), "optional private sample check")
class PrivateReferenceTests(unittest.TestCase):
    def test_reference_pair(self):
        root = Path(os.environ["ENERGY_LOGGER_PRIVATE_DATA"])
        info = convert.parse_info((root / "A05FD3D5.BIN").read_bytes())
        data = (root / "A05FD3D6.BIN").read_bytes()
        result = convert.parse_measurements(data)
        self.assertEqual(len(result.records), 1458)
        self.assertTrue(all(r.valid for r in result.records))
        self.assertEqual(len(result.records) / 60, 24.3)
        self.assertEqual(info.total_energy_kwh, .476)
        self.assertAlmostEqual(max(r.active_power for r in result.records), 604.16048)
        self.assertAlmostEqual(result.energy_estimate_kwh, .4474703195166667)
        self.assertEqual(sum(r.timestamp is None for r in result.records), 1456)
        backfilled = convert.parse_measurements(data, backfill_timestamps=True)
        self.assertEqual(backfilled.records[-1].timestamp - backfilled.records[0].timestamp,
                         timedelta(minutes=1457))


if __name__ == "__main__":
    unittest.main()
