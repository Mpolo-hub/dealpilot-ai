"""Holdout log, head record and lock (spec 003 section 9.4, D12).

The log is append only and hash-chained; the head record is a local checkpoint. This module
never rebuilds, resets, truncates or rewrites a log, never removes a lock it did not just
create, and never writes the incident record (section 9.8).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dealpilot.forecasting.records import sha256_text
from dealpilot.forecasting.split import ForecastingError

COLUMNS = ("seq", "timestamp_utc", "event", "run_id", "config_hash", "commit", "data_hash",
           "holdout_start", "holdout_end", "result", "prev_sha256")
HEADER = ",".join(COLUMNS)
STARTED, COMPLETED = "started", "completed"
NORMAL = "normal"
# Integrity failures, in the order used when several apply (section 9.4, Precedence).
PRECEDENCE = ("B", "C", "D", "F", "E", "G")
HOLDOUT_MARK = "-holdout-"

_HEX64 = re.compile(r"[0-9a-f]{64}")
_HEX40 = re.compile(r"[0-9a-f]{40}")
_SEQ = re.compile(r"[1-9][0-9]*")
_RUN_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-holdout-[0-9a-f]{8}(-[0-9]{1,2})?")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_HEAD = re.compile(rb"([1-9][0-9]*),([0-9a-f]{64})\n")


class HoldoutRefused(ForecastingError):
    """A holdout run refused before step 4: nothing appended, holdout not consumed."""


@dataclass(frozen=True)
class Entry:
    seq: int
    timestamp_utc: str
    event: str
    run_id: str
    config_hash: str
    commit: str
    data_hash: str
    holdout_start: str
    holdout_end: str
    result: str
    prev_sha256: str
    line_sha256: str

    def line(self) -> str:
        return ",".join(str(getattr(self, c)) for c in COLUMNS)


@dataclass(frozen=True)
class StartedRecord:
    """An identifiable `started` entry: enough to establish consumption (section 9.4)."""
    run_id: str
    data_hash: str
    holdout_start: str
    holdout_end: str


@dataclass
class LogInspection:
    state: str  # NORMAL, "A" or one of PRECEDENCE
    reasons: list[str] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)  # parsed entries (valid log only)
    started: list[StartedRecord] = field(default_factory=list)  # identifiable, any state
    completed: dict[str, str] = field(default_factory=dict)  # run_id -> result

    @property
    def usable(self) -> bool:
        return self.state in (NORMAL, "A")

    @property
    def head(self) -> tuple[int, str] | None:
        if not self.entries:
            return None
        return self.entries[-1].seq, self.entries[-1].line_sha256


def entry_line(seq: int, timestamp: str, event: str, run_id: str, config_hash: str,
               commit: str, data_hash: str, holdout_start: str, holdout_end: str,
               result: str, prev_sha256: str) -> str:
    values = (str(seq), timestamp, event, run_id, config_hash, commit, data_hash,
              holdout_start, holdout_end, result, prev_sha256)
    if any(ch in v for v in values for ch in ",\r\n"):
        raise ForecastingError("a holdout log value contains a separator")
    return ",".join(values)


def head_bytes(seq: int, line_sha256: str) -> bytes:
    return f"{seq},{line_sha256}\n".encode("ascii")


def _is_date(text: str) -> bool:
    try:
        return date.fromisoformat(text).isoformat() == text
    except ValueError:
        return False


def _identifiable(fields: list[str]) -> StartedRecord | None:
    """Question (1) of section 9.4: own event, run_id and data_hash readable."""
    if len(fields) != len(COLUMNS):
        return None
    row = dict(zip(COLUMNS, fields))
    if row["event"] != STARTED or not _RUN_ID.fullmatch(row["run_id"]) \
            or not _HEX64.fullmatch(row["data_hash"]):
        return None
    return StartedRecord(row["run_id"], row["data_hash"], row["holdout_start"],
                         row["holdout_end"])


def _field_problem(row: dict) -> str | None:
    if not _SEQ.fullmatch(row["seq"]):
        return "seq is not a decimal integer"
    if not _TIMESTAMP.fullmatch(row["timestamp_utc"]):
        return "timestamp_utc is malformed"
    if row["event"] not in (STARTED, COMPLETED):
        return "event is neither started nor completed"
    if not _RUN_ID.fullmatch(row["run_id"]):
        return "run_id is malformed"
    for name in ("config_hash", "data_hash", "prev_sha256"):
        if not _HEX64.fullmatch(row[name]):
            return f"{name} is not 64 lowercase hex characters"
    if not _HEX40.fullmatch(row["commit"]):
        return "commit is malformed"
    if not (_is_date(row["holdout_start"]) and _is_date(row["holdout_end"])):
        return "holdout dates are malformed"
    expected = ("",) if row["event"] == STARTED else ("pass", "fail")
    if row["result"] not in expected:
        return "result does not match the event"
    return None


def _holdout_folders(results_dir: Path) -> list[str]:
    if not results_dir.is_dir():
        return []
    return sorted(p.name for p in results_dir.iterdir() if p.is_dir() and HOLDOUT_MARK in p.name)


def inspect_log(log_path: Path, head_path: Path, results_dir: Path) -> LogInspection:
    """Classify the log and head record (states A to G), then run checks 1 to 5.

    Read-only. Anything that cannot be read or classified with certainty is an integrity
    failure; nothing is ever guessed.
    """
    try:
        return _inspect(log_path, head_path, results_dir)
    except OSError as error:
        return LogInspection("F", [f"unreadable: {type(error).__name__}"])


def _inspect(log_path: Path, head_path: Path, results_dir: Path) -> LogInspection:
    log_exists = os.path.lexists(log_path)
    head_exists = os.path.lexists(head_path)
    if not log_exists:
        if head_exists:
            return LogInspection("C", ["log absent, head record present"])
        folders = _holdout_folders(results_dir)
        if folders:
            return LogInspection("B", [f"holdout-stage run folder exists: {folders[0]}"])
        return LogInspection("A")
    if not log_path.is_file():
        return LogInspection("F", ["the log is not a regular file"])
    raw = log_path.read_bytes()
    found = LogInspection(NORMAL)
    # Question (1): identifiable `started` entries, whatever else is wrong.
    complete = raw.split(b"\n")[:-1] if raw else []
    for raw_line in complete[1:]:
        try:
            record = _identifiable(raw_line.decode("utf-8").split(","))
        except UnicodeDecodeError:
            record = None
        if record is not None:
            found.started.append(record)

    if raw == (HEADER + "\n").encode("utf-8"):
        found.state = "D"
        found.reasons.append("the log holds only the header line")
        return found
    problem = _malformed(raw, found)
    if problem:
        found.state = "F"
        found.reasons.append(problem)
        found.entries = []
        return found
    if not head_exists:
        found.state = "E"
        found.reasons.append("head record missing (check 5)")
        return found
    head = head_path.read_bytes() if head_path.is_file() else b""
    match = _HEAD.fullmatch(head)
    if not match:
        found.state = "G"
        found.reasons.append("head record unreadable (check 5)")
        return found
    seq, digest = int(match.group(1)), match.group(2).decode("ascii")
    if (seq, digest) != found.head:
        found.state = "G"
        found.reasons.append("head record does not match the last entry (check 5)")
    return found


def _malformed(raw: bytes, found: LogInspection) -> str | None:
    """State F checks, then checks 1 to 4. Fills `found.entries` and `found.completed`."""
    if not raw:
        return "the log file is empty"
    if not raw.endswith(b"\n"):
        return "the last line has no LF (partial line)"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "the log is not valid UTF-8"
    lines = text[:-1].split("\n")
    if lines[0] != HEADER:
        return "wrong header (check 1)"
    previous = lines[0]
    started_ids: set[str] = set()
    for number, line in enumerate(lines[1:], start=1):
        fields = line.split(",")
        if len(fields) != len(COLUMNS):
            return f"line {number + 1} has {len(fields)} fields"
        row = dict(zip(COLUMNS, fields))
        problem = _field_problem(row)
        if problem:
            return f"line {number + 1}: {problem}"
        if int(row["seq"]) != number:
            return f"line {number + 1}: seq is not {number} (check 2)"
        if row["prev_sha256"] != sha256_text(previous):
            return f"line {number + 1}: prev_sha256 does not match (check 3)"
        run_id = row["run_id"]
        if row["event"] == STARTED:
            if run_id in started_ids:
                return f"line {number + 1}: second started entry for {run_id} (check 4)"
            started_ids.add(run_id)
        else:
            if run_id not in started_ids:
                return f"line {number + 1}: completed without started (check 4)"
            if run_id in found.completed:
                return f"line {number + 1}: second completed entry for {run_id} (check 4)"
            found.completed[run_id] = row["result"]
        found.entries.append(Entry(int(row["seq"]), row["timestamp_utc"], row["event"],
                                   run_id, row["config_hash"], row["commit"],
                                   row["data_hash"], row["holdout_start"],
                                   row["holdout_end"], row["result"], row["prev_sha256"],
                                   sha256_text(line)))
        previous = line
    return None


def consumed(inspection: LogInspection, data_hash_value: str, holdout_start: str,
             holdout_end: str) -> bool:
    """Only an identifiable `started` entry establishes consumption (section 5.3)."""
    return any(r.data_hash == data_hash_value and r.holdout_start == holdout_start
               and r.holdout_end == holdout_end for r in inspection.started)


def run_states(inspection: LogInspection, results_dir: Path) -> dict[str, str]:
    """Reported state of every `run_id` with an identifiable `started` entry."""
    states = {}
    for record in inspection.started:
        run_json = results_dir / record.run_id / "run.json"
        if record.run_id not in inspection.completed:
            states[record.run_id] = "interrupted"
        elif run_json.is_file():
            states[record.run_id] = "completed"
        else:
            states[record.run_id] = "completed, record incomplete"
    return states


def status_report(log_path: Path, head_path: Path, lock_path: Path,
                  results_dir: Path) -> dict:
    """Read-only report of the log state, the lock and every run's state."""
    inspection = inspect_log(log_path, head_path, results_dir)
    return {"state": inspection.state, "reasons": list(inspection.reasons),
            "lock_present": os.path.lexists(lock_path),
            "runs": run_states(inspection, results_dir),
            "results": dict(inspection.completed)}


# --------------------------------------------------------------------------- writing

def create_lock(lock_path: Path) -> None:
    """Step 1: create the lock exclusively; an existing lock refuses the run."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(lock_path, "x", encoding="ascii", newline="\n") as handle:
            handle.write("holdout run in progress\n")
    except FileExistsError:
        raise HoldoutRefused("holdout lock present (integrity failure)") from None


def remove_lock(lock_path: Path) -> None:
    """Only for the run's own lock: after step 7, or after a refusal before step 4."""
    lock_path.unlink()


def _fsync(handle) -> None:
    """Separate so tests can inject a failed `fsync`."""
    handle.flush()
    os.fsync(handle.fileno())


def append_entry(log_path: Path, line: str, first_use: bool) -> None:
    """Append one entry and sync it; on first use create the log with its header first."""
    data = (line + "\n").encode("utf-8")
    if first_use:
        with open(log_path, "xb") as handle:  # refuses if the log now exists
            handle.write((HEADER + "\n").encode("utf-8") + data)
            _fsync(handle)
    else:
        with open(log_path, "ab") as handle:
            handle.write(data)
            _fsync(handle)


def write_head(head_path: Path, seq: int, line_sha256: str) -> None:
    """Write the head record to a temporary name, sync it, then rename it into place."""
    temporary = head_path.with_name(head_path.name + ".tmp")
    with open(temporary, "wb") as handle:
        handle.write(head_bytes(seq, line_sha256))
        _fsync(handle)
    os.replace(temporary, head_path)
