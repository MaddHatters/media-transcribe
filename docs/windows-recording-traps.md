# Windows Recording Traps

Known pitfalls when running the media-transcribe recording pipeline on the OBS Windows machine (`Matt@100.66.194.100`).

## 1. Disconnected RDP Session (Critical)

**Symptom:** OBS launches but WebSocket never responds. Preflight fails on OBS WebSocket gate.

**Root cause:** Someone RDP'd into the machine and closed the RDP window without logging out. This creates a "Disconnected" session. When `schtasks /it` launches OBS, it runs on the disconnected desktop session — not the console session with the physical HDMI display and GPU access. OBS can't render or respond.

**Detection:**
```powershell
query user
# Look for State = "Disc" (disconnected)
```

**Fix:**
```powershell
# Reconnect the disconnected session to the physical console
tscon <session_id> /dest:console
# Example: tscon 2 /dest:console
```

**Prevention:**
- When using RDP, **log out** (Start > Sign out) instead of just closing the RDP window
- The `setup` command should auto-detect disconnected sessions and reconnect them before launching OBS
- Consider adding a `tscon` guard to `_launch_obs_with_dialog_handler()` in `src/capture/environment.py`

**TODO:** Add session reconnect to preflight/setup flow automatically.

---

## 2. OBS Crash Dialog Blocking Startup (Critical)

**Symptom:** OBS process starts but never initializes (no new log entries, WebSocket port closed). The process sits at 0% CPU.

**Root cause:** After `taskkill /f /im obs64.exe` (force kill), OBS detects an unclean shutdown on next launch and shows a blocking "Crash Detected" dialog with two buttons: "Run in Safe Mode" and "Run in Normal Mode". This dialog must be dismissed before OBS continues starting.

**Detection:**
```powershell
# OBS running but no new log content = stuck on dialog
Get-Process obs64  # Shows process running
# But latest log in %APPDATA%\obs-studio\logs\ has only "Crash or unclean shutdown detected"
```

**Mitigation (current):**
- `_clean_obs_crash_markers()` sets `LastCrashState=false` in `global.ini` and appends shutdown marker to last log
- `_launch_obs_with_dialog_handler()` uses a smart launcher with `SetCursorPos` + `mouse_event` to click "Run in Normal Mode"
- Both are unreliable on disconnected desktops (see Trap #1)

**Prevention:**
- **Never force-kill OBS.** Use graceful shutdown instead:
  ```python
  # Via WebSocket (preferred)
  client = obs.ReqClient(host='localhost', port=4455, password='...')
  client.stop_record()  # if recording
  # OBS doesn't have a native "quit" via WebSocket, use:
  ```
  ```powershell
  # Via PowerShell — sends WM_CLOSE (like clicking X)
  Get-Process obs64 | ForEach-Object { $_.CloseMainWindow() }
  ```
- Only use `taskkill /f` as absolute last resort, and always run `_clean_obs_crash_markers()` + session reconnect before next launch

**TODO:** Replace all `taskkill /f /im obs64.exe` calls with graceful `CloseMainWindow()` approach.

---

## 3. System Python vs Venv Python (Medium)

**Symptom:** `python cli.py preflight` reports OBS WebSocket FAIL even though OBS is running and the port is open.

**Root cause:** The OBS machine has Python 3.8-32bit as system Python. The `obsws_python` package is only installed in the project's `.venv`. When `cli.py` is run with system Python, the WebSocket connection attempt uses a different library path or times out.

**Fix:** Always use the venv Python:
```powershell
# Correct
C:\Users\Matt\transcribe\.venv\Scripts\python.exe C:\Users\Matt\transcribe\cli.py preflight

# Incorrect (may fail on WebSocket checks)
python C:\Users\Matt\transcribe\cli.py preflight
```

**TODO:** The scheduled tasks and SSH commands should use the venv Python explicitly, or `cli.py` should auto-activate the venv.

---

## 4. cp1252 Encoding Crash on Emoji (Fixed)

**Symptom:** `cli.py discover` crashes with `UnicodeEncodeError: 'charmap' codec can't encode character` when printing post titles containing emoji.

**Root cause:** Windows console defaults to cp1252 encoding, which can't encode emoji Unicode characters.

**Fix (applied):** Added UTF-8 reconfigure at the top of `cli.py`:
```python
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass
```

Also set `PYTHONIOENCODING=utf-8` when running commands over SSH.

---

## 5. SCP Recursive Copy Doesn't Overwrite (Medium)

**Symptom:** After `scp -r` to sync source files to the OBS machine, some files retain their old content. Import errors occur because updated files weren't actually updated.

**Root cause:** `scp -r` on Windows doesn't reliably overwrite existing files in subdirectories. Some files silently keep their old content.

**Fix:** Use git-based deployment instead of SCP:
```powershell
# On OBS machine
git -C C:\Users\Matt\transcribe pull origin main
```

**Prevention:** The git deployment strategy (`DEPLOY.md`) replaces ad-hoc SCP. All source changes go through git.

---

## 6. PowerShell Quoting with schtasks (Low)

**Symptom:** `schtasks /create /tr "C:\Program Files\obs-studio\..."` fails with "Invalid argument" when the path contains spaces.

**Root cause:** PowerShell's string escaping interacts badly with `schtasks` argument parsing. Nested quotes get mangled.

**Fix:** Write a `.bat` file with the command, then point `schtasks /tr` at the bat file:
```powershell
Set-Content C:\Users\Matt\launch_obs.bat -Value '@echo off
"C:\Program Files\obs-studio\bin\64bit\obs64.exe" --minimize-to-tray'

schtasks /create /tn OBS_Launch /tr C:\Users\Matt\launch_obs.bat /sc once /st 00:00 /f /it /ru Matt
```

---

## 7. SSH Command Timeouts (Medium)

**Symptom:** Long-running SSH commands (OBS setup, full catalog discovery, recording) hit the 120s timeout and get backgrounded or killed.

**Root cause:** The orchestrator's SSH commands have a default 120s timeout. OBS startup can take 90s+ (crash dialog wait), and recordings can run for hours.

**Mitigation:** Use longer timeouts for known slow commands, or run commands via scheduled tasks on the Windows machine rather than blocking on SSH.

**TODO:** Create an orchestrator skill for queuing long-running SSH tasks that monitors via polling instead of blocking.

---

## Quick Reference: Preflight Checklist

Before recording, verify:

1. **Desktop session is active on console:** `query user` — State should be `Active`, SESSIONNAME should be `console`
2. **Using venv Python:** `.venv\Scripts\python.exe` not system `python`
3. **OBS WebSocket responding:** `Test-NetConnection -ComputerName localhost -Port 4455`
4. **Patreon session valid:** Preflight checks this automatically
5. **Disk space:** 300+ GB recommended for multi-hour recordings
