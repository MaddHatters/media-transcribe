"""Tests for src/transcribe/corrections — rule loading and application."""
from pathlib import Path

from src.transcribe.corrections import load_rules, apply_rules


def test_load_rules_empty_file(tmp_path):
    rules_file = tmp_path / "empty.txt"
    rules_file.write_text("")
    assert load_rules(rules_file) == []


def test_load_rules_comments_only(tmp_path):
    rules_file = tmp_path / "comments.txt"
    rules_file.write_text("# just a comment\n# another\n")
    assert load_rules(rules_file) == []


def test_load_rules_literal(tmp_path):
    rules_file = tmp_path / "rules.txt"
    rules_file.write_text("foo => BAR\n")
    rules = load_rules(rules_file)
    assert len(rules) == 1


def test_load_rules_regex(tmp_path):
    rules_file = tmp_path / "rules.txt"
    rules_file.write_text("re:\\bD[JG]I F\\b => DGIF\n")
    rules = load_rules(rules_file)
    assert len(rules) == 1


def test_apply_rules_literal():
    rules = load_rules(Path("transcribe/corrections.txt"))
    text = "I bought d grow and S CHD today"
    result, counts = apply_rules(text, rules)
    assert "DGRO" in result
    assert "SCHD" in result


def test_apply_rules_idempotent():
    rules = load_rules(Path("transcribe/corrections.txt"))
    text = "I bought DGRO and SCHD today"
    result, counts = apply_rules(text, rules)
    assert result == text
    assert not counts


def test_apply_rules_regex():
    rules = load_rules(Path("transcribe/corrections.txt"))
    text = "The DJI F strategy is good"
    result, _ = apply_rules(text, rules)
    assert "DGIF" in result


def test_load_rules_inline_comment(tmp_path):
    rules_file = tmp_path / "rules.txt"
    rules_file.write_text("foo => BAR  # this is a comment\n")
    rules = load_rules(rules_file)
    assert len(rules) == 1
    result, counts = apply_rules("foo", rules)
    assert "BAR" in result


def test_load_rules_missing_file():
    rules = load_rules(Path("/nonexistent/rules.txt"))
    assert rules == []
