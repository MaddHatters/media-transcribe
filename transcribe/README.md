# transcribe — media to transcripts

Local, offline transcription with **Whisper** via
[`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) (CTranslate2).
Free, private, no API key; weights download once (~1.5 GB) and are cached.

## Run

```bash
uv sync
# recommended: turbo model, 4 videos in parallel
uv run transcribe/transcribe.py "/mnt/secondary/media/patreon/FIRE Investing Masterclass" \
    --model large-v3-turbo --workers 4 --cpu-threads 4
```

Outputs `<name>.txt` (clean prose) and `<name>.srt` (timestamps) into
`<folder>/transcripts/`. Resumable: files with both outputs are skipped.

Useful flags: `--only "Masterclass 13"` (substring filter), `--model large-v3`
(max quality), `--beam-size 1` (faster, slightly lower), `--out DIR`.

## Model choice (measured on this content)

| Model | Quality | Speed |
|-------|---------|-------|
| `large-v3-turbo` | equal to large-v3 on clear English (sometimes cleaner) | ~2x faster — **use this** |
| `large-v3` | reference quality | ~2x realtime single-stream |

Accuracy on clear lecture audio is excellent (~3-7% WER). A Silero VAD filter
suppresses silence hallucinations; `finance_vocab.txt` is fed as the
`initial_prompt` to bias proper nouns.

## Tickers & coined acronyms: the correction dictionary

Whisper gets the prose but mangles a few recurring symbols regardless of model —
`DGRO` -> "d grow", `SCHD` -> "S CHD", and the instructor's coined "DGF" ->
`DJI`/`DGI F`. The robust fix is `corrections.txt`, a deterministic per-course
find/replace dictionary applied automatically on write (and re-runnable
standalone). On Masterclass 13 it corrected 29 ticker/acronym instances.

Format (literal, case-insensitive, whole-word; or `re:` for raw regex):

```
d grow => DGRO
S CHD  => SCHD
re:\bD[JG]I ?F\b => DGF
```

Re-apply to existing transcripts after editing the dictionary (idempotent):

```bash
uv run transcribe/apply_corrections.py "<transcripts-folder>" --dry-run   # preview
uv run transcribe/apply_corrections.py "<transcripts-folder>"             # write
```

Disable during transcription with `--corrections ''`. Note: corrections apply
per subtitle segment, so a symbol split across an `.srt` segment boundary (e.g.
"…to S" / "CHD…") is caught in the joined `.txt` but may survive in the `.srt`.

## Speed levers

- **Parallelism** (`--workers`) is the biggest free win on a many-core CPU —
  a single Whisper stream scales poorly past ~4-8 threads.
- `large-v3-turbo` ~2x; `--beam-size 1` ~2x; both stack.
- No usable GPU here (AMD iGPU; ROCm + CTranslate2 is not viable).

### Apple Silicon alternative

On an M-series Mac, `faster-whisper` is CPU-only — use `mlx-whisper` for GPU/ANE
acceleration. Same weights = same quality. Only worth it to offload this box,
and the videos would need to move to the Mac first.
