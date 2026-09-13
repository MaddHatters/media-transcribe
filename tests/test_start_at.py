"""Tests for --start-at deferred execution feature."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from cli import build_parser, wait_until


class TestStartAtArgumentParsing:
    def test_pipeline_accepts_start_at(self):
        parser = build_parser()
        args = parser.parse_args(["pipeline", "--queue", "/tmp/q.json", "--start-at", "22:00"])
        assert args.start_at == "22:00"

    def test_record_accepts_start_at(self):
        parser = build_parser()
        args = parser.parse_args(["record", "--queue", "/tmp/q.json", "--start-at", "22:00"])
        assert args.start_at == "22:00"

    def test_pipeline_start_at_defaults_to_none(self):
        parser = build_parser()
        args = parser.parse_args(["pipeline", "--queue", "/tmp/q.json"])
        assert args.start_at is None

    def test_record_start_at_defaults_to_none(self):
        parser = build_parser()
        args = parser.parse_args(["record", "--queue", "/tmp/q.json"])
        assert args.start_at is None

    def test_start_at_stores_full_datetime_string(self):
        parser = build_parser()
        args = parser.parse_args(["pipeline", "--queue", "/tmp/q.json", "--start-at", "2026-09-05 03:00"])
        assert args.start_at == "2026-09-05 03:00"


class TestWaitUntilParsing:
    @patch("cli.time.sleep")
    @patch("cli.datetime")
    def test_hhmm_format_correct_target(self, mock_dt, mock_sleep):
        mock_dt.now.return_value = datetime(2026, 9, 1, 14, 0)
        mock_dt.strptime.side_effect = datetime.strptime
        result = wait_until("22:00")
        assert result == 0
        mock_sleep.assert_called_once()
        delta = mock_sleep.call_args[0][0]
        assert 28700 < delta < 28900  # ~8 hours

    @patch("cli.time.sleep")
    @patch("cli.datetime")
    def test_hhmm_past_rolls_to_tomorrow(self, mock_dt, mock_sleep):
        mock_dt.now.return_value = datetime(2026, 9, 1, 23, 30)
        mock_dt.strptime.side_effect = datetime.strptime
        result = wait_until("22:00")
        assert result == 0
        mock_sleep.assert_called_once()
        delta = mock_sleep.call_args[0][0]
        assert 80900 < delta < 81100  # ~22.5 hours

    @patch("cli.time.sleep")
    @patch("cli.datetime")
    def test_full_datetime_format(self, mock_dt, mock_sleep):
        mock_dt.now.return_value = datetime(2026, 9, 1, 14, 0)
        mock_dt.strptime.side_effect = datetime.strptime
        result = wait_until("2026-09-05 03:00")
        assert result == 0
        mock_sleep.assert_called_once()

    @patch("cli.time.sleep")
    @patch("cli.datetime")
    def test_full_datetime_past_no_sleep(self, mock_dt, mock_sleep):
        mock_dt.now.return_value = datetime(2026, 9, 1, 14, 0)
        mock_dt.strptime.side_effect = datetime.strptime
        result = wait_until("2026-01-01 10:00")
        assert result == 0
        mock_sleep.assert_not_called()

    @patch("cli.time.sleep")
    @patch("cli.datetime")
    def test_invalid_format_returns_error(self, mock_dt, mock_sleep, capsys):
        mock_dt.now.return_value = datetime(2026, 9, 1, 14, 0)
        mock_dt.strptime.side_effect = datetime.strptime
        result = wait_until("not-a-time")
        assert result == 1
        mock_sleep.assert_not_called()
        output = capsys.readouterr().out
        assert "Invalid --start-at format" in output


class TestWaitUntilSleepBehavior:
    @patch("cli.time.sleep")
    @patch("cli.datetime")
    def test_positive_delta_calls_sleep(self, mock_dt, mock_sleep):
        mock_dt.now.return_value = datetime(2026, 9, 1, 14, 0)
        mock_dt.strptime.side_effect = datetime.strptime
        wait_until("15:00")
        mock_sleep.assert_called_once()
        delta = mock_sleep.call_args[0][0]
        assert 3500 < delta < 3700  # ~1 hour

    @patch("cli.time.sleep")
    @patch("cli.datetime")
    def test_negative_delta_no_sleep(self, mock_dt, mock_sleep):
        mock_dt.now.return_value = datetime(2026, 9, 1, 14, 0)
        mock_dt.strptime.side_effect = datetime.strptime
        wait_until("2026-08-31 10:00")
        mock_sleep.assert_not_called()

    @patch("cli.os.getpid", return_value=12345)
    @patch("cli.time.sleep")
    @patch("cli.datetime")
    def test_print_output_includes_target_delta_pid(self, mock_dt, mock_sleep, mock_getpid, capsys):
        mock_dt.now.return_value = datetime(2026, 9, 1, 14, 0)
        mock_dt.strptime.side_effect = datetime.strptime
        wait_until("22:00")
        output = capsys.readouterr().out
        assert "2026-09-01 22:00" in output
        assert "hours" in output
        assert "12345" in output


class TestWaitUntilEdgeCases:
    @patch("cli.time.sleep")
    @patch("cli.datetime")
    def test_month_boundary_rollover(self, mock_dt, mock_sleep):
        mock_dt.now.return_value = datetime(2026, 1, 31, 23, 30)
        mock_dt.strptime.side_effect = datetime.strptime
        result = wait_until("23:00")
        assert result == 0
        mock_sleep.assert_called_once()
        delta = mock_sleep.call_args[0][0]
        assert 84500 < delta < 84700  # ~23.5 hours (rolls to Feb 1)

    @patch("cli.time.sleep")
    @patch("cli.datetime")
    def test_midnight_works(self, mock_dt, mock_sleep):
        mock_dt.now.return_value = datetime(2026, 9, 1, 22, 0)
        mock_dt.strptime.side_effect = datetime.strptime
        result = wait_until("00:00")
        assert result == 0
        mock_sleep.assert_called_once()
        delta = mock_sleep.call_args[0][0]
        assert 7100 < delta < 7300  # ~2 hours (rolls to tomorrow midnight)
