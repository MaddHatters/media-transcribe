"""Tests for the new-video ingest runner."""
from ingest_new import ingest


def _fake_transcribe(video, out_dir):
    """Stub that creates .txt + .srt without running Whisper."""
    (out_dir / f"{video.stem}.txt").write_text("transcript")
    (out_dir / f"{video.stem}.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")


def test_transcribes_only_missing(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("A.mkv", "B.mkv", "C.mkv"):
        (source / name).touch()

    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / "A.txt").write_text("done")
    (transcripts / "A.srt").write_text("done")

    result = ingest(source, transcripts, transcribe_fn=_fake_transcribe)

    assert result == ["B", "C"]
    assert (transcripts / "B.txt").exists()
    assert (transcripts / "B.srt").exists()
    assert (transcripts / "C.txt").exists()
    assert (transcripts / "C.srt").exists()


def test_rerun_is_noop(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("A.mkv", "B.mkv", "C.mkv"):
        (source / name).touch()

    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    for stem in ("A", "B", "C"):
        (transcripts / f"{stem}.txt").write_text("done")
        (transcripts / f"{stem}.srt").write_text("done")

    calls = []

    def _counting_fake(video, out_dir):
        calls.append(video.stem)
        _fake_transcribe(video, out_dir)

    result = ingest(source, transcripts, transcribe_fn=_counting_fake)

    assert result == []
    assert calls == []
