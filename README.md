# media-transcribe

Local, private pipeline for turning a library of videos into searchable
transcripts (and, optionally, OCR'd slide text). Built for the FIRE Investing
Masterclass, reusable for any video folder.

Two stages, kept separate:

```
acquire/      get the source media          ->   transcribe/   media -> transcripts
├ obs_capture.py    real-browser + OBS (Windows)   ├ transcribe.py    Whisper large-v3 / turbo
└ patreon_download.sh  yt-dlp direct (faster)       └ finance_vocab.txt
```

## The pipeline

1. **Acquire** the media. Either record real playback with OBS (safe, real-time —
   see `acquire/README.md`) or download directly with `yt-dlp` (faster, small
   ToS risk). For transcripts you only need audio; capture video too if you want
   slide OCR later.
2. **Transcribe** locally on the CPU with Whisper — free, offline, no API key
   (see `transcribe/README.md`). `large-v3-turbo` is the recommended model:
   near-identical to `large-v3` on clear English, ~2x faster.

## Quick start (transcription only, if you already have the videos)

```bash
uv sync
uv run transcribe/transcribe.py "/mnt/secondary/FIRE Investing Masterclass" \
    --model large-v3-turbo --workers 4 --cpu-threads 4
```

Outputs `.txt` + `.srt` into a `transcripts/` subfolder next to the videos.

## Hardware notes

- Transcription box: AMD Ryzen 9 9955HX (16 cores). Run several videos in
  parallel (`--workers 4 --cpu-threads 4`) — far faster than one video on all
  16 threads. Measured ~2x realtime single-stream; ~5-6x aggregate.
- Capture box: any idle GUI machine (an older Windows PC is ideal — capture is
  light and real-time, so power doesn't matter; you just don't want to tie up a
  machine you need).
