import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.services.node import compute_push_raw
from app.utils import parse_json_array, parse_json_object, parse_utc_datetime


class LineProtocolTests(unittest.TestCase):
    def test_empty_field_set_is_skipped(self):
        from app.metrics import _build_line_protocol

        self.assertEqual(
            _build_line_protocol("device_metric", {"device_id": "1"}, {}),
            "",
        )


class RawDecompressionTests(unittest.TestCase):
    def test_bounded_decompression_rejects_oversized_output(self):
        import brotli

        from app.services.device import _decompress_bounded

        raw = brotli.compress(b"\0" * (32 * 1024 * 1024))
        self.assertIsNone(_decompress_bounded(raw, 1024 * 1024))

    def test_bounded_decompression_round_trips_valid_output(self):
        import brotli

        from app.services.device import _decompress_bounded

        payload = b"smartctl output\n" * 100
        self.assertEqual(
            _decompress_bounded(brotli.compress(payload), 1024 * 1024), payload
        )


class UtilityTests(unittest.TestCase):
    def test_parse_utc_datetime_accepts_iso_fractional_seconds(self) -> None:
        parsed = parse_utc_datetime("2026-08-19T12:34:56.123456+00:00")

        self.assertEqual(parsed, datetime(2026, 8, 19, 12, 34, 56, 123456, tzinfo=timezone.utc))

    def test_json_helpers_validate_collection_type(self) -> None:
        self.assertEqual(parse_json_array('[1, 2]'), [1, 2])
        self.assertIsNone(parse_json_array('{"items": []}'))
        self.assertEqual(parse_json_object('{"items": []}'), {"items": []})
        self.assertIsNone(parse_json_object('[1, 2]'))


class RawPushScheduleTests(unittest.TestCase):
    def test_iso_timestamp_written_by_api_is_used_for_schedule(self) -> None:
        now = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
        last_push = (now - timedelta(days=1, seconds=1)).isoformat()

        with patch("app.services.node.settings.global_raw_push_base", "day"), patch(
            "app.services.node.settings.global_raw_push_freq", 1
        ):
            self.assertTrue(compute_push_raw({"last_raw_push": last_push}, now))


if __name__ == "__main__":
    unittest.main()
