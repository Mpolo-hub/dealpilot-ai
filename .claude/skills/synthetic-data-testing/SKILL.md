---
name: synthetic-data-testing
description: Verify the DealPilot synthetic sales data generator (spec 001) and its reference dataset. Use after any change to backend/src/dealpilot/data/, its tests, specs/001-synthetic-sales-data.md, pyproject.toml or requirements-dev.lock, and before relying on data/raw for API or forecasting work. Covers seed-42 regeneration into a temp folder, byte-for-byte comparison with data/raw, metadata and row-count checks, invalid date ranges, ruff, the default and slow pytest suites, and the clean-venv lock check.
---

# Synthetic data testing

Source of truth: `specs/001-synthetic-sales-data.md` (acceptance criteria AC-01 to AC-17,
section 8; decisions, section 9). Tests: `backend/tests/test_ac_*.py`, `conftest.py`.
Do not copy thresholds into code or reports from memory: read them from the spec.

## Hard rules
- **Never write to `data/raw`** while verifying. It is the seed-42 reference dataset
  (`D:\DealPilot AI\data\raw`, ignored by git). Regenerate into a temp folder outside the
  repo (session scratchpad or `$env:TEMP`) and delete it afterwards.
- **Never adjust an acceptance threshold, formula or seed to make a test pass.** Report the
  failure and investigate (spec 001 section 9, P2 rules). AC-12's thresholds are still
  **provisional** (spec 001 section 8 note and P3); changing them needs a spec update and
  explicit approval.
- Never commit generated datasets, temp verification output, `.venv/` or secrets.
- Use the venv's Python 3.13 for everything (`backend\.venv\Scripts\python.exe`), never
  the system Python 3.14.

## Workflow (PowerShell; adjust quoting for bash)

### 1. Regenerate seed 42 into a temp folder (from the project root)
```powershell
Set-Location -LiteralPath 'D:\DealPilot AI'
$tmp = Join-Path $env:TEMP ("dealpilot-verify-" + (Get-Date -Format 'HHmmss'))
backend\.venv\Scripts\python.exe -m dealpilot.data.generate --seed 42 --out $tmp
```
Expect exit 0 and the row counts printed on one line.

### 2. Byte-for-byte comparison with the reference (all eight files)
```powershell
backend\.venv\Scripts\python.exe -c "import filecmp, pathlib, sys; ref, new = pathlib.Path('data/raw'), pathlib.Path(sys.argv[1]); names = sorted(p.name for p in ref.iterdir()); diff = [n for n in names if not (new / n).is_file() or not filecmp.cmp(ref / n, new / n, shallow=False)]; extra = sorted({p.name for p in new.iterdir()} - set(names)); print(len(names), 'reference files; differ:', diff or 'none', '; extra:', extra or 'none'); sys.exit(1 if diff or extra or len(names) != 8 else 0)" $tmp
```
Pass: `8 reference files; differ: none ; extra: none`, exit 0. The eight files are the seven
Parquet tables plus `metadata.json`. A difference means generator output changed: find
out why before doing anything else. Byte identity also depends on the locked numpy and
pyarrow versions (`metadata.json` records them in `library_versions`).

### 3. Metadata and row counts
```powershell
backend\.venv\Scripts\python.exe -c "import duckdb, json, pathlib, sys; d = pathlib.Path(sys.argv[1]); m = json.loads((d / 'metadata.json').read_text(encoding='utf-8')); print('seed', m['seed'], m['start'], '..', m['end'], 'version', m['generator_version']); got = {t: duckdb.read_parquet(str(d / (t + '.parquet'))).aggregate('count(*)').fetchall()[0][0] for t in m['row_counts']}; bad = {t: (m['row_counts'][t], got[t]) for t in got if got[t] != m['row_counts'][t]}; print('row_counts match parquet:', not bad, bad or ''); sys.exit(1 if bad else 0)" $tmp
```
Expect seed 42, 2023-01-01 to 2025-12-31, and every `row_counts` entry equal to the real
table size. The metadata schema is spec 001 section 3.1; the seed-42 counts appear in
`specs/002-api.md` (5.2 example, AC-API-04).

### 4. Invalid date ranges (spec 001 AC-14)
```powershell
foreach ($end in '2024-12-29', '2026-01-01') {
  $bad = Join-Path $env:TEMP ("dealpilot-verify-bad-" + $end)
  backend\.venv\Scripts\python.exe -m dealpilot.data.generate --start 2023-01-01 --end $end --out $bad 2>$null
  "end=$end exit=$LASTEXITCODE written=$(Test-Path -LiteralPath $bad)"
}
```
Expect `exit=2 written=False` for both (729 and 1,097 days).

### 5. Lint and tests (from `backend/`)
```powershell
Set-Location -LiteralPath 'D:\DealPilot AI\backend'
.\.venv\Scripts\python.exe -m ruff check --no-respect-gitignore src tests
.\.venv\Scripts\python.exe -m pytest            # default suite (AC-10 excluded)
.\.venv\Scripts\python.exe -m pytest -m slow    # AC-10: 10 generator runs, about 1 minute
```
- Use `--no-respect-gitignore`: ruff skips git-ignored files, and a broad `.gitignore`
  rule once hid `backend/src/dealpilot/data/` from both git and ruff. Confirm the linted
  file count equals the `.py` files on disk (`--show-files`). The ruff config includes the
  `S` security rules, and `pytest` runs `tests/test_security.py`, which also checks that
  `data/` stays git-ignored and the generator source stays visible.
- All tests must pass with 0 errors. Determinism is covered by AC-03/AC-04; step 2 adds a
  byte-level check against the stored reference.
- `pytest -m slow -s` prints AC-10's per-seed table and pooled D. Per-seed D values are
  diagnostics only; only the pooled D gates. The tests don't print AC-09 L or AC-12 OD
  and CV_res; when those values are needed, compute them in a throwaway script outside
  the repo, following spec 001 sections 8.1 and 8.2 exactly.

### 6. Clean up
```powershell
backend\.venv\Scripts\python.exe -c "import shutil, sys; shutil.rmtree(sys.argv[1])" $tmp
```
Delete only the temp folders you created. Never delete or regenerate `data/raw` unless
explicitly asked; to recreate it, run from the project root:
`backend\.venv\Scripts\python.exe -m dealpilot.data.generate --seed 42 --out data/raw`.

## When dependencies or the lock file change
Verify reproducibility in a **separate** venv before touching the working `.venv`:
```powershell
Set-Location -LiteralPath 'D:\DealPilot AI\backend'
$venv = Join-Path $env:TEMP ("dealpilot-cleanvenv-" + (Get-Date -Format 'HHmmss'))
py -3.13 -m venv $venv
& "$venv\Scripts\python.exe" -m pip install -r requirements-dev.lock
& "$venv\Scripts\python.exe" -m pip install --no-deps -e .
& "$venv\Scripts\python.exe" -m pip check
& "$venv\Scripts\python.exe" -m ruff check --no-respect-gitignore src tests
& "$venv\Scripts\python.exe" -m pytest
```
Then confirm `pip freeze --exclude-editable` matches between the clean and working venvs
(ignore CRLF differences on Windows), and that a seed-42 run from the clean venv is
byte-identical to `data/raw` (steps 1 and 2 with that venv's Python).

## Report
State the exact commands, exit codes and results: byte comparison (8 of 8), row counts,
invalid-range exits, ruff file count, pytest pass/fail/error counts and runtimes, and
any AC-09/AC-10/AC-12 values you measured, next to their spec ranges. Say which values
you did not measure and which checks could not run (and why); never present an unrun
check as passed. List anything provisional or unresolved.
