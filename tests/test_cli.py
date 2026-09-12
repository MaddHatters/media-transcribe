"""Tests for cli.py — argument parsing for each subcommand."""
import pytest

from src.config import CATALOG_PATH


def test_cli_transcribe_args():
    """Test that transcribe subcommand accepts expected arguments."""
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["transcribe", "/tmp/videos", "--model", "tiny", "--only", "test"])
    assert args.command == "transcribe"
    assert args.folder == "/tmp/videos"
    assert args.model == "tiny"
    assert args.only == "test"


def test_cli_analyze_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["analyze", "/tmp/videos", "--single", "test.mkv"])
    assert args.command == "analyze"
    assert args.folder == "/tmp/videos"
    assert args.single == "test.mkv"


def test_cli_correct_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["correct", "/tmp/transcripts", "--dry-run"])
    assert args.command == "correct"
    assert args.dry_run is True


def test_cli_find_gaps_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["find-gaps", "/tmp/transcripts"])
    assert args.command == "find-gaps"


def test_cli_pipeline_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["pipeline", "--queue", "/tmp/q.json", "--steps", "transcribe,correct"])
    assert args.command == "pipeline"
    assert args.queue == "/tmp/q.json"
    assert args.steps == "transcribe,correct"


def test_cli_preflight_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["preflight"])
    assert args.command == "preflight"


def test_cli_extract_frames_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["extract-frames", "--gaps", "gaps.yaml", "--videos", "/tmp", "--out", "/tmp/frames"])
    assert args.command == "extract-frames"


def test_cli_transfer_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["transfer-transcripts", "--apply-corrections"])
    assert args.command == "transfer-transcripts"
    assert args.apply_corrections is True


def test_cli_no_subcommand():
    from cli import build_parser
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_cli_record_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["record", "--queue", "/tmp/q.json"])
    assert args.command == "record"
    assert args.queue == "/tmp/q.json"


def test_cli_screenshot_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["screenshot"])
    assert args.command == "screenshot"


def test_cli_release_info_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["release-info"])
    assert args.command == "release-info"


def test_cli_status_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["status"])
    assert args.command == "status"


# --- catalog-refresh ---

def test_cli_catalog_refresh_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["catalog-refresh"])
    assert args.command == "catalog-refresh"
    assert args.catalog == str(CATALOG_PATH)
    assert args.campaign_id == "5008493"
    assert args.full is False
    assert args.force is False


def test_cli_catalog_refresh_full():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["catalog-refresh", "--full", "--force"])
    assert args.full is True
    assert args.force is True


# --- --from-catalog ---

def test_cli_pipeline_from_catalog_default():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["pipeline", "--from-catalog"])
    assert args.command == "pipeline"
    assert args.from_catalog == str(CATALOG_PATH)
    assert args.queue is None


def test_cli_pipeline_from_catalog_custom_path():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["pipeline", "--from-catalog", "/tmp/my_catalog.json"])
    assert args.from_catalog == "/tmp/my_catalog.json"


def test_cli_pipeline_queue_still_works():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["pipeline", "--queue", "/tmp/q.json"])
    assert args.queue == "/tmp/q.json"
    assert args.from_catalog is None


def test_cli_pipeline_from_catalog_and_queue_mutually_exclusive():
    """Both --from-catalog and --queue should return error code 1."""
    from unittest.mock import patch
    from cli import main
    with patch("sys.argv", ["cli.py", "pipeline", "--from-catalog", "--queue", "/tmp/q.json",
                            "--foreground"]):
        rc = main()
    assert rc == 1


def test_cli_pipeline_neither_flag_returns_error():
    """Neither --from-catalog nor --queue should return error code 1."""
    from unittest.mock import patch
    from cli import main
    with patch("sys.argv", ["cli.py", "pipeline", "--foreground"]):
        rc = main()
    assert rc == 1
