# Plan: Release / Deploy Workflow

## Task Description
Build a release/deploy workflow for the media-transcribe project. The project is developed on devbox-01 (Linux) and deployed to the obs-machine (Windows) via SCP over Tailscale SSH. This plan covers:
1. A `scripts/release.sh` shell script that runs tests, deploys, and verifies
2. A `cli.py release-info` subcommand for deploy introspection
3. Version tracking via `src/__version__`
4. Documentation updates to AGENTS.md
5. Tests for all new functionality

## Objective
Provide a repeatable, safe one-command release workflow (`bash scripts/release.sh`) that tests locally, deploys to obs-machine, verifies the deploy, and prints a summary. Add `release-info` to the CLI for checking what's deployed.

## Problem Statement
Deployment is currently a manual multi-step process: run pytest, run a multi-line SCP command, SSH to install deps, manually verify. There's no version tracking, no pre-flight safety checks (branch, clean tree, reachability), and no way to introspect what's currently deployed on the obs-machine.

## Solution Approach
- Shell script for the orchestration layer (it coordinates SSH, SCP, and local pytest — not Python-level work)
- Python for the `release-info` CLI subcommand (follows existing argparse patterns in cli.py)
- `importlib.metadata` for version at runtime (reads from pyproject.toml's installed metadata, no duplication)
- Tests mock all SSH/SCP calls so they run offline on devbox-01

## Relevant Files
Use these files to complete the task:

- **`cli.py`** — Add `release-info` subcommand parser and dispatch. Follows existing argparse pattern with `sub.add_parser()` and `if/elif` dispatch chain.
- **`src/__init__.py`** — Currently empty. Add `__version__` using `importlib.metadata`.
- **`src/config.py`** — Contains `SSH_HOST = "Matt@100.66.194.100"` and other constants. Reference for SSH target; may add `REMOTE_PROJECT_DIR` constant.
- **`pyproject.toml`** — Already has `version = "0.1.0"`. No changes needed (importlib.metadata reads from here at runtime).
- **`AGENTS.md`** — Add "Release / Deploy" section documenting the workflow.
- **`tests/test_cli.py`** — Add `test_cli_release_info_args()` following existing pattern.

### New Files
- **`scripts/release.sh`** — The release/deploy shell script (new directory `scripts/`).
- **`tests/test_release_info.py`** — Tests for the `release-info` subcommand and version import.

## Implementation Phases

### Phase 1: Foundation
Add version tracking to `src/__init__.py` using `importlib.metadata`. This is the simplest change and unblocks both the release script (prints version) and the CLI subcommand.

### Phase 2: Core Implementation
Create `scripts/release.sh` with pre-flight checks, test execution, SCP deploy, remote dep install, post-deploy verification, and summary output. Add the `release-info` subcommand to `cli.py`.

### Phase 3: Integration & Polish
Write tests, update AGENTS.md documentation, and validate the full workflow end-to-end.

## Step by Step Tasks
IMPORTANT: Execute every step in order, top to bottom.

### 1. Add version tracking to `src/__init__.py`
- Add `__version__` that reads from `importlib.metadata.version("media-transcribe")`, with a fallback to `"0.1.0-dev"` if the package isn't installed (e.g., running from source without `uv sync`):
  ```python
  from importlib.metadata import version, PackageNotFoundError

  try:
      __version__ = version("media-transcribe")
  except PackageNotFoundError:
      __version__ = "0.1.0-dev"
  ```
- This avoids duplicating the version string — pyproject.toml remains the single source of truth.

### 2. Create `scripts/release.sh`
- Create the `scripts/` directory.
- Write `scripts/release.sh` with the following sections. Use `set -euo pipefail` and define constants at the top:

  ```bash
  #!/usr/bin/env bash
  set -euo pipefail

  REMOTE="Matt@100.66.194.100"
  REMOTE_DIR="C:/Users/Matt/transcribe"
  ```

- **Parse flags**: Support `--verify` flag (default: off). Use a simple loop over `$@`.

- **Section 1 — Pre-flight checks**:
  - Check current branch is `main`: `git rev-parse --abbrev-ref HEAD` must equal `main`. Print error and exit 1 if not.
  - Check working tree is clean: `git diff --quiet && git diff --cached --quiet`. Print error and exit 1 if dirty.
  - Check obs-machine is reachable: `ssh -o ConnectTimeout=5 "$REMOTE" "echo ok"`. Print error and exit 1 if unreachable.
  - Print version from: `uv run python -c "from src import __version__; print(__version__)"`
  - Print git commit hash: `git rev-parse --short HEAD`

- **Section 2 — Run tests**:
  - Run `uv run pytest` and capture exit code.
  - If tests fail, print failure message and exit 1.
  - Print test summary (pytest already outputs this; just gate on exit code).

- **Section 3 — Deploy**:
  - SCP files to obs-machine:
    ```bash
    scp -r src/ cli.py pyproject.toml launch_chrome.bat \
      transcribe/corrections.txt transcribe/finance_vocab.txt \
      "$REMOTE:$REMOTE_DIR/"
    ```
  - Run `uv sync --extra capture` on obs-machine via SSH:
    ```bash
    ssh "$REMOTE" "cd $REMOTE_DIR; uv sync --extra capture"
    ```
  - Print deployed file count: `ssh "$REMOTE" "cd $REMOTE_DIR; dir /s /b src\*.py | find /c /v \"\""`
    - Alternatively, use PowerShell: `(Get-ChildItem -Path src -Recurse -Filter *.py).Count`
  - Print timestamp.

- **Section 4 — Post-deploy verification**:
  - Verify deployed version matches local:
    ```bash
    LOCAL_VER=$(uv run python -c "from src import __version__; print(__version__)")
    REMOTE_VER=$(ssh "$REMOTE" "cd $REMOTE_DIR; uv run python -c \"from src import __version__; print(__version__)\"")
    ```
    Compare and warn if mismatch.
  - Run `uv run cli.py --help` on obs-machine to verify no import errors:
    ```bash
    ssh "$REMOTE" "cd $REMOTE_DIR; uv run cli.py --help"
    ```
  - If `--verify` flag was passed, also run preflight:
    ```bash
    ssh "$REMOTE" "cd $REMOTE_DIR; uv run cli.py preflight"
    ```

- **Section 5 — Summary**:
  - Print a clear block with: version, git hash, deploy target, timestamp.
  - Print the pipeline command hint:
    ```
    To run pipeline:
      ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py pipeline --queue <file>"
    ```

- Make the script executable: `chmod +x scripts/release.sh`.

**Important details for the script**:
- SSH to obs-machine drops into PowerShell. Use `;` to chain commands, not `&&`.
- All `ssh` commands must use the `$REMOTE` variable for consistency.
- Use colored output helpers (green for success, red for failure, yellow for warnings) via simple functions that echo ANSI codes. Check `[ -t 1 ]` before using color.
- Each section should print a header line (e.g., `==> Pre-flight checks`) for readability.

### 3. Add `release-info` subcommand to `cli.py`
- In `build_parser()`, add the subcommand after the `screenshot` parser:
  ```python
  sub.add_parser("release-info", help="Show version, commit, and deploy status")
  ```

- In `main()`, add the dispatch branch before the final `return 0`:
  ```python
  elif args.command == "release-info":
      from src import __version__
      import subprocess as _sp

      commit = _sp.run(
          ["git", "rev-parse", "--short", "HEAD"],
          capture_output=True, text=True,
      ).stdout.strip() or "unknown"

      print(f"Version:  {__version__}")
      print(f"Commit:   {commit}")
      print(f"Target:   Matt@100.66.194.100:C:/Users/Matt/transcribe/")

      result = _sp.run(
          ["ssh", "-o", "ConnectTimeout=5", "Matt@100.66.194.100",
           "cd C:\\Users\\Matt\\transcribe; uv run python -c "
           "\"from src import __version__; print(__version__)\""],
          capture_output=True, text=True,
      )
      if result.returncode == 0:
          remote_ver = result.stdout.strip()
          print(f"Deployed: {remote_ver}")
      else:
          print("Deployed: (unreachable)")
  ```

- Use `SSH_HOST` from `src.config` instead of hardcoding where appropriate. The remote dir can be introduced as a constant `REMOTE_PROJECT_DIR = "C:/Users/Matt/transcribe"` in `src/config.py`.

### 4. Add `REMOTE_PROJECT_DIR` to `src/config.py`
- Add below the existing `SSH_HOST` line:
  ```python
  REMOTE_PROJECT_DIR = "C:/Users/Matt/transcribe"
  ```
- Use this in the `release-info` subcommand for the target display and SSH command construction.

### 5. Write tests

**`tests/test_release_info.py`**:

- **`test_version_importable`**: Verify `from src import __version__` works and returns a string matching semver pattern:
  ```python
  def test_version_importable():
      from src import __version__
      assert isinstance(__version__, str)
      assert __version__  # non-empty
  ```

- **`test_cli_release_info_args`**: Verify argparse accepts the subcommand:
  ```python
  def test_cli_release_info_args():
      from cli import build_parser
      parser = build_parser()
      args = parser.parse_args(["release-info"])
      assert args.command == "release-info"
  ```

- **`test_release_info_output`**: Test the `main()` dispatch prints expected output. Mock `subprocess.run` to avoid real git/ssh calls:
  ```python
  from unittest.mock import patch, MagicMock

  def test_release_info_output(capsys):
      mock_result = MagicMock()
      mock_result.stdout = "abc1234\n"
      mock_result.returncode = 0

      with patch("subprocess.run", return_value=mock_result):
          from cli import main
          import sys
          with patch.object(sys, "argv", ["cli.py", "release-info"]):
              main()

      captured = capsys.readouterr()
      assert "Version:" in captured.out
      assert "Commit:" in captured.out
      assert "Target:" in captured.out
  ```

- **`test_release_info_remote_unreachable`**: Test that when SSH fails, it prints "(unreachable)" gracefully:
  ```python
  def test_release_info_remote_unreachable(capsys):
      fail_result = MagicMock()
      fail_result.returncode = 1
      fail_result.stdout = ""

      git_result = MagicMock()
      git_result.stdout = "abc1234\n"
      git_result.returncode = 0

      def side_effect(cmd, **kwargs):
          if cmd[0] == "ssh":
              return fail_result
          return git_result

      with patch("subprocess.run", side_effect=side_effect):
          import sys
          from cli import main
          with patch.object(sys, "argv", ["cli.py", "release-info"]):
              main()

      captured = capsys.readouterr()
      assert "(unreachable)" in captured.out
  ```

**Add to `tests/test_cli.py`**:
- Add `test_cli_release_info_args` following the existing pattern (same as above, but in the existing test file for consistency).

**Test the release script is executable**:
  ```python
  import os

  def test_release_script_executable():
      script = Path(__file__).parent.parent / "scripts" / "release.sh"
      assert script.exists(), "scripts/release.sh must exist"
      assert os.access(script, os.X_OK), "scripts/release.sh must be executable"
  ```

### 6. Update AGENTS.md
- Add a new `## Release / Deploy` section after the existing `### Deployment` subsection (or as a new top-level section before `## Infrastructure`). Content:

  ```markdown
  ## Release / Deploy

  One-command deploy from devbox-01 to obs-machine:

  ```bash
  bash scripts/release.sh            # test → deploy → verify
  bash scripts/release.sh --verify   # also runs preflight on obs-machine
  ```

  The script:
  1. Checks you're on `main` with a clean working tree
  2. Verifies obs-machine is reachable via SSH
  3. Runs `uv run pytest` — aborts on failure
  4. SCPs project files to `C:\Users\Matt\transcribe\`
  5. Runs `uv sync --extra capture` on obs-machine
  6. Verifies deployed version matches local
  7. Runs `cli.py --help` on obs-machine to check imports

  ### Checking deploy status

  ```bash
  uv run cli.py release-info    # shows version, commit, deploy target, remote version
  ```

  ### After deploying

  ```bash
  ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py pipeline --queue <file>"
  ```
  ```

### 7. Validate everything
- Run `uv run pytest` to ensure all tests pass (existing + new).
- Run `uv run python -c "from src import __version__; print(__version__)"` to verify version import.
- Run `bash -n scripts/release.sh` to syntax-check the shell script.
- Run `chmod +x scripts/release.sh && ls -la scripts/release.sh` to verify executable bit.

## Testing Strategy

- **Unit tests** for the `release-info` CLI subcommand: argparse acceptance, output format with mocked subprocess, graceful handling of unreachable remote.
- **Import test** for `src.__version__`: ensures `importlib.metadata` integration works.
- **Script existence/permission test**: ensures `scripts/release.sh` exists and is executable.
- **All SSH/SCP calls are mocked** in tests — no network dependency.
- **No integration test for the shell script itself** — it's validated via `bash -n` (syntax check) and manual testing. The script is simple enough that section-by-section review suffices.

## Acceptance Criteria

- [ ] `from src import __version__` returns `"0.1.0"` (or `"0.1.0-dev"` if not installed)
- [ ] `scripts/release.sh` exists, is executable, and passes `bash -n` syntax check
- [ ] `scripts/release.sh` includes all 5 sections: pre-flight, test, deploy, verify, summary
- [ ] `scripts/release.sh --verify` triggers preflight on obs-machine
- [ ] `uv run cli.py release-info` prints version, commit, target, and remote status
- [ ] `uv run cli.py release-info` handles unreachable obs-machine gracefully (prints "(unreachable)")
- [ ] AGENTS.md has a "Release / Deploy" section documenting the workflow
- [ ] All existing tests continue to pass
- [ ] New tests cover: version import, CLI args, release-info output, unreachable remote, script permissions
- [ ] `uv run pytest` passes with 0 failures

## Validation Commands
Execute these commands to validate the task is complete:

- `uv run pytest` — All tests pass (existing + new)
- `uv run python -c "from src import __version__; print(__version__)"` — Prints version string
- `uv run cli.py release-info` — Prints version/commit/target (remote may be unreachable from devbox during dev)
- `bash -n scripts/release.sh` — Shell script has valid syntax
- `test -x scripts/release.sh && echo "executable" || echo "not executable"` — Script is executable
- `grep -q "Release / Deploy" AGENTS.md && echo "documented" || echo "missing"` — AGENTS.md updated

## Notes
- No new dependencies needed. `importlib.metadata` is stdlib (Python 3.8+).
- The release script uses `uv run pytest` (not `pytest` directly) to match the project convention.
- SSH to obs-machine uses PowerShell — always use `;` to chain commands, never `&&`.
- The `--verify` flag is off by default because preflight requires Chrome and OBS to be running on the obs-machine, which isn't always the case.
- The deploy file list (`src/`, `cli.py`, `pyproject.toml`, `launch_chrome.bat`, `transcribe/corrections.txt`, `transcribe/finance_vocab.txt`) matches the app registry's `deploy_cmd`. Do NOT include `.env`, cookies, browser profiles, or media files.
- `subprocess` is already imported at the top of `cli.py` — the `release-info` branch can use it directly. However, the dispatch branch uses a local `import subprocess as _sp` to avoid shadowing the top-level import which is only used in `background_relaunch`. Actually, `subprocess` is already imported at the top level in cli.py (line 24), so just use it directly — no need for a local import alias.
