"""Tests for the transcript correction engine and the shipped dictionary."""
from pathlib import Path

import pytest

from corrections import apply_rules, load_rules

DICT_PATH = Path(__file__).resolve().parent.parent / "transcribe" / "corrections.txt"


# --------------------------------------------------------------------------- #
# load_rules
# --------------------------------------------------------------------------- #
def write_rules(tmp_path, text):
    p = tmp_path / "rules.txt"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_skips_comments_blanks_and_malformed(tmp_path):
    rules = load_rules(write_rules(tmp_path, """
        # a full-line comment
        d grow => DGRO        # inline comment
        this line has no arrow

        re:\\bD[JG]I ?F\\b => DGF
    """.replace("        ", "")))
    assert len(rules) == 2


def test_missing_file_returns_empty(tmp_path):
    assert load_rules(tmp_path / "nope.txt") == []


# --------------------------------------------------------------------------- #
# apply_rules — literal
# --------------------------------------------------------------------------- #
@pytest.fixture
def literal(tmp_path):
    return load_rules(write_rules(tmp_path, "d grow => DGRO\nS CHD => SCHD\n"))


def test_literal_is_case_insensitive(literal):
    out, _ = apply_rules("change D grow to s chd today", literal)
    assert out == "change DGRO to SCHD today"


def test_literal_is_whole_word_only(literal):
    # must not fire inside a larger token
    out, counts = apply_rules("downgrowth and SCHDX are fine", literal)
    assert out == "downgrowth and SCHDX are fine"
    assert counts == {}


def test_counts_are_reported(literal):
    _, counts = apply_rules("d grow, d grow, S CHD", literal)
    assert counts == {"DGRO": 2, "SCHD": 1}


# --------------------------------------------------------------------------- #
# apply_rules — DGIF variants (regex requires a space so it never touches the
# already-correct "DGIF" — keeps corrections idempotent)
# --------------------------------------------------------------------------- #
@pytest.fixture
def dgif(tmp_path):
    return load_rules(write_rules(tmp_path, "re:\\bD[JG]I F\\b => DGIF\nDJIF => DGIF\n"))


@pytest.mark.parametrize("variant", ["DJI F", "DGI F", "DJIF"])
def test_regex_catches_dgif_variants(dgif, variant):
    out, _ = apply_rules(f"buy {variant} now", dgif)
    assert out == "buy DGIF now"


def test_correct_dgif_is_left_unchanged(dgif):
    # the canonical spelling must NOT be re-matched (idempotency)
    out, counts = apply_rules("buy DGIF now", dgif)
    assert out == "buy DGIF now"
    assert counts == {}


def test_regex_leaves_standalone_dgi_alone(dgif):
    # "DGI" (dividend growth investing) must survive; only the F-variant is DGIF
    out, counts = apply_rules("DGI funds and DGI strategy", dgif)
    assert out == "DGI funds and DGI strategy"
    assert counts == {}


# --------------------------------------------------------------------------- #
# idempotency + the real shipped dictionary
# --------------------------------------------------------------------------- #
def test_apply_is_idempotent(tmp_path):
    rules = load_rules(DICT_PATH)
    mangled = "QQQ, VU and d grow, switch d grow to S CHD. DJF and DJI F are great. I love DGI."
    once, _ = apply_rules(mangled, rules)
    twice, counts = apply_rules(once, rules)
    assert once == twice
    assert counts == {}


def test_real_dictionary_fixes_known_mangles():
    rules = load_rules(DICT_PATH)
    assert rules, "shipped corrections.txt should load rules"
    mangled = "switch d grow to S CHD; DJF and DJI F differ from DGI"
    out, _ = apply_rules(mangled, rules)
    assert "DGRO" in out and "SCHD" in out and "DGIF" in out
    # the mangled spellings are gone (incl. the old "DGF" contraction)
    for bad in ("d grow", "S CHD", "DJF", "DJI F", "DGF"):
        assert bad not in out
    # the legitimate, distinct term is preserved
    assert "DGI" in out
