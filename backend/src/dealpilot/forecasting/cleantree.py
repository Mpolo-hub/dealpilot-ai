"""Formal-run clean-tree check (spec 003 section 9.5, O2 plan in section 13.3).

`check_clean_tree` gives one of three outcomes and never raises:
- CLEAN: every check passed, nothing changed and no conflict;
- DIRTY: the repository can be trusted, but files changed or conflicts exist;
- REFUSED: a foundational check failed, the result can't be trusted, or anything
  unexpected happened. Foundational failures stop at once; nothing after them runs.

pygit2 (the optional `formal` extra, internal use only) is imported only inside this
function, so no other part of DealPilot needs it. No subprocess and no private pygit2 or
libgit2 interface is used (D14). The controller does not lock the repository: it detects
changes to the index, HEAD, the operation state, the configuration and lock files between
its first and last checks, but not every concurrent change to the working tree.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dealpilot.forecasting.gitindex import (
    MODE_SYMLINK,
    IndexRejected,
    IndexSnapshot,
    check_path_text,
    read_index,
    safe_text,
)

CLEAN, DIRTY, REFUSED = "CLEAN", "DIRTY", "REFUSED"
CHECKER = "pygit2"
COMPATIBILITY_PROFILE = "o2-windows-v1"
MAX_PATH_CHARS = 259
# Not yet established by the AC-FC-26 parity tests (section 13.3): refuse until then.
ALLOW_NON_ASCII_PATHS = False

# C1: variables Git honours but libgit2 ignores without GIT_REPOSITORY_OPEN_FROM_ENV.
FORBIDDEN_ENV = frozenset({
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_CONFIG", "GIT_CONFIG_NOSYSTEM",
    "GIT_CONFIG_SYSTEM", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS",
})
FORBIDDEN_ENV_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
# C2: files only libgit2 reads (sysdir.c), relative to an environment folder.
LIBGIT2_ONLY_FILES = (("APPDATA", "git/config"), ("APPDATA", "git/ignore"),
                      ("APPDATA", "git/attributes"), ("LOCALAPPDATA", "git/config"),
                      ("LOCALAPPDATA", "git/ignore"), ("LOCALAPPDATA", "git/attributes"),
                      ("PROGRAMDATA", "Git/config"))
LOCK_FILES = ("index.lock", "HEAD.lock", "config.lock", "packed-refs.lock", "shallow.lock")
# Folders searched for `*.lock` at any depth (loose objects themselves are never scanned).
LOCK_FOLDERS = ("refs", "logs", "objects/info", "objects/pack")
_INCLUDE_HEADER = re.compile(r"^\s*\[\s*include(if)?(\s|\"|\.|\])", re.IGNORECASE)
# Keys that make Git write index extensions the reader refuses, or that change the layout.
_TRUE_REFUSED = ("core.sparsecheckout", "core.sparsecheckoutcone", "index.sparse",
                 "feature.manyfiles", "core.splitindex", "index.skiphash",
                 "index.recordendofindexentries", "index.recordoffsettable", "core.bare")
_PRESENT_REFUSED = ("index.threads", "core.worktree", "core.excludesfile",
                    "core.attributesfile", "core.eol")
_RECORDED = ("core.autocrlf", "core.eol", "core.safecrlf", "core.ignorecase", "core.filemode",
             "core.symlinks", "core.longpaths", "core.fscache", "core.excludesfile",
             "core.attributesfile")


@dataclass(frozen=True)
class CleanTreeResult:
    outcome: str
    commit: str | None = None
    head_detached: bool | None = None
    changed_paths: tuple[str, ...] = ()
    conflict_paths: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    checker: str = CHECKER
    checker_version: str | None = None
    libgit2_version: str | None = None
    index_version: int | None = None
    index_sha256: str | None = None
    index_extensions: tuple[str, ...] = ()
    effective_config: dict[str, str | None] = field(default_factory=dict)
    config_levels_present: dict[str, bool] = field(default_factory=dict)
    compatibility_profile: str = COMPATIBILITY_PROFILE

    @property
    def clean(self) -> bool:
        return self.outcome == CLEAN

    def provenance(self) -> dict:
        """The `git_provenance` record of `run.json` (spec 003 sections 9.3 and 13.3)."""
        return {
            "outcome": self.outcome, "clean_tree": self.clean, "commit": self.commit,
            "head_detached": self.head_detached, "changed_paths": list(self.changed_paths),
            "conflict_paths": list(self.conflict_paths), "reasons": list(self.reasons),
            "checker": self.checker, "checker_version": self.checker_version,
            "libgit2_version": self.libgit2_version, "index_version": self.index_version,
            "index_sha256": self.index_sha256, "index_extensions": list(self.index_extensions),
            "effective_config": dict(self.effective_config),
            "config_levels_present": dict(self.config_levels_present),
            "compatibility_profile": self.compatibility_profile,
        }


class _Refused(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.reason = f"{code}: {detail}" if detail else code


@dataclass
class _State:
    root: Path
    gitdir: Path
    facts: dict = field(default_factory=dict)


# Errors turned into REFUSED. pygit2.GitError is handled where pygit2 is used. Anything
# else is a programming error: it propagates, and a caller treats any exception as "not
# clean" (spec 003 section 13.3); it can never produce CLEAN.
_ERRORS = (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError,
           RuntimeError, LookupError, ArithmeticError, MemoryError, ImportError)


def check_clean_tree(project_root: Path) -> CleanTreeResult:
    """Run phases A, B and C. Expected errors give REFUSED; nothing gives CLEAN by default."""
    state = None
    try:
        root = Path(project_root).resolve()
        state = _State(root, root / ".git")
        return _run(state)
    except _Refused as refused:
        return _refused(state, refused.reason)
    except _ERRORS as error:
        return _refused(state, f"unexpected_error: {type(error).__name__}")


def _refused(state: _State | None, reason: str) -> CleanTreeResult:
    facts = state.facts if state is not None else {}
    keep = {k: facts[k] for k in ("commit", "head_detached", "checker_version",
                                  "libgit2_version", "index_version", "index_sha256",
                                  "index_extensions", "effective_config",
                                  "config_levels_present") if k in facts}
    return CleanTreeResult(REFUSED, reasons=(reason,), **keep)


def _import_pygit2():
    """Separate so tests can simulate a missing checker."""
    return importlib.import_module("pygit2")


def _status(repo) -> dict:
    """Separate so tests can simulate concurrent changes during the scan."""
    return repo.status(untracked_files="all", ignored=False)


# --------------------------------------------------------------------------- phases

def _run(state: _State) -> CleanTreeResult:
    # Phase A: foundational checks; the first failure stops everything.
    _check_environment()
    _check_root(state)
    _check_locks(state.gitdir)
    first = _snapshot(state)
    pygit2 = _load_checker(state)
    try:
        return _run_with_checker(state, pygit2, first)
    except pygit2.GitError as error:
        raise _Refused("git_error", type(error).__name__) from None


def _run_with_checker(state: _State, pygit2, first: IndexSnapshot) -> CleanTreeResult:
    repo = _open_repository(pygit2, state)
    config_hashes = _check_configuration(pygit2, repo, state, first)
    target = _check_repository(pygit2, repo, state)

    # Phase B: collect changes and conflicts; unexpected results stop at once.
    changed, status_conflicts = _collect_status(pygit2, repo, state)
    conflicts = _check_conflicts(repo, first, status_conflicts)

    # Phase C: integrity; any failure replaces DIRTY with REFUSED.
    if repo.head.target != target:
        raise _Refused("head_changed_during_check")
    if repo.state() != _enums(pygit2).RepositoryState.NONE:
        raise _Refused("operation_started_during_check")
    if _hash_files(config_hashes) != config_hashes:
        raise _Refused("configuration_changed_during_check")
    _check_locks(state.gitdir)
    second = _snapshot(state)
    if (second.sha256, second.stat) != (first.sha256, first.stat):
        raise _Refused("index_changed_during_check")
    _check_locks(state.gitdir)

    reasons = []
    if changed:
        reasons.append("changes_present")
    if conflicts:
        reasons.append("conflicts_present")
    facts = state.facts
    return CleanTreeResult(
        DIRTY if reasons else CLEAN, commit=facts["commit"],
        head_detached=facts["head_detached"], changed_paths=tuple(sorted(changed)),
        conflict_paths=tuple(sorted(conflicts)), reasons=tuple(reasons),
        checker_version=facts["checker_version"], libgit2_version=facts["libgit2_version"],
        index_version=first.version, index_sha256=first.sha256,
        index_extensions=first.extensions, effective_config=facts["effective_config"],
        config_levels_present=facts["config_levels_present"])


def _enums(pygit2):
    return importlib.import_module("pygit2.enums")


def _check_environment() -> None:
    """C1 and C2, plus ambiguous global configuration folders."""
    for name in os.environ:
        upper = name.upper()
        if upper in FORBIDDEN_ENV or upper.startswith(FORBIDDEN_ENV_PREFIXES):
            raise _Refused("forbidden_environment_variable", upper)
    for variable, relative in LIBGIT2_ONLY_FILES:
        base = os.environ.get(variable)
        if base and (Path(base) / relative).exists():
            raise _Refused("libgit2_only_config_file", f"%{variable}%/{relative}")
    folders = {os.path.normcase(str(Path(p).resolve())) for p in _home_candidates()}
    if sum((Path(folder) / ".gitconfig").exists() for folder in folders) > 1:
        raise _Refused("ambiguous_global_config")


def _home_candidates() -> list[str]:
    env = os.environ
    candidates = [env.get("HOME"), env.get("USERPROFILE")]
    if env.get("HOMEDRIVE") and env.get("HOMEPATH"):
        candidates.append(env["HOMEDRIVE"] + env["HOMEPATH"])
    return [c for c in candidates if c]


def _check_root(state: _State) -> None:
    if os.name != "nt":
        raise _Refused("unsupported_platform", "the O2 profile covers Windows only")
    gitdir = state.gitdir
    if gitdir.is_symlink() or not gitdir.is_dir():
        raise _Refused("no_repository_at_root")
    if (gitdir / "commondir").exists():
        raise _Refused("linked_worktree")


def _check_locks(gitdir: Path) -> None:
    for name in LOCK_FILES:
        if (gitdir / name).exists():
            raise _Refused("git_lock_present", name)
    if any(p.suffix == ".lock" for p in gitdir.iterdir()):
        raise _Refused("git_lock_present", "*.lock")
    for name in LOCK_FOLDERS:
        folder = gitdir / name
        if folder.is_dir() and any(p.suffix == ".lock" for p in folder.rglob("*")):
            raise _Refused("git_lock_present", f"{name}/*.lock")


def _snapshot(state: _State) -> IndexSnapshot:
    try:
        snapshot = read_index(state.gitdir / "index")
    except IndexRejected as rejected:
        raise _Refused(rejected.code, rejected.detail) from None
    for entry in snapshot.entries:
        _check_path(state.root, entry.path)
        if entry.mode == MODE_SYMLINK:  # K4: core.symlinks=false with symlinks is untested
            raise _Refused("symlink_entry", safe_text(entry.path))
    state.facts.update(index_version=snapshot.version, index_sha256=snapshot.sha256,
                       index_extensions=snapshot.extensions)
    return snapshot


def _check_path(root: Path, path: str) -> None:
    """Section 13.3 path policy for tracked and untracked paths alike."""
    try:
        check_path_text(path)
    except IndexRejected as rejected:
        raise _Refused(rejected.code, rejected.detail) from None
    if not ALLOW_NON_ASCII_PATHS and not path.isascii():
        raise _Refused("non_ascii_path", safe_text(path))
    if len(str(root / path)) > MAX_PATH_CHARS:
        raise _Refused("path_too_long", safe_text(path))


def _load_checker(state: _State):
    try:
        pygit2 = _import_pygit2()
    except (ImportError, OSError):  # missing, or a native module that fails to load
        raise _Refused("checker_unavailable") from None
    state.facts.update(checker_version=getattr(pygit2, "__version__", None),
                       libgit2_version=getattr(pygit2, "LIBGIT2_VERSION", None))
    return pygit2


def _open_repository(pygit2, state: _State):
    enums = _enums(pygit2)
    try:
        repo = pygit2.Repository(str(state.root), enums.RepositoryOpenFlag.NO_SEARCH)
    except (pygit2.GitError, KeyError, ValueError, OSError):
        found = _discover(pygit2, state.root)
        raise _Refused("parent_repository" if found else "repository_open_failed") from None
    workdir = repo.workdir
    if not workdir or os.path.normcase(str(Path(workdir).resolve())) != os.path.normcase(
            str(state.root)):
        raise _Refused("workdir_not_project_root")
    return repo


def _discover(pygit2, root: Path) -> str | None:
    """Only to explain a refusal (for example a repository in a parent folder)."""
    try:
        return pygit2.discover_repository(str(root))
    except (pygit2.GitError, KeyError, ValueError, OSError):
        return None


# --------------------------------------------------------------------------- configuration

def _git_bool(value: str | None) -> bool:
    """Git boolean syntax; anything else is ambiguous and refused."""
    if value is None:
        return True  # `[core] key` with no `=` means true
    text = value.strip().lower()
    if text in ("true", "yes", "on", "1"):
        return True
    if text in ("false", "no", "off", "0", ""):
        return False
    raise _Refused("ambiguous_config_value", safe_text(value))


def _is_false(value: str | None) -> bool:
    """True only for a value Git reads as boolean false, in any letter case."""
    try:
        return _git_bool(value) is False
    except _Refused:
        return False


def _candidate_config_files(pygit2, gitdir: Path) -> list[Path]:
    """Every file libgit2 may read, present or not, so phase C also sees a new one."""
    enums = _enums(pygit2)
    files = [gitdir / "config", gitdir / "config.worktree"]
    names = ((enums.ConfigLevel.SYSTEM, "gitconfig"), (enums.ConfigLevel.GLOBAL, ".gitconfig"),
             (enums.ConfigLevel.XDG, "config"), (enums.ConfigLevel.PROGRAMDATA, "config"))
    system_files = []
    for level, name in names:
        for folder in (pygit2.settings.search_path[level] or "").split(os.pathsep):
            if folder:
                path = Path(folder) / name
                files.append(path)
                if level == enums.ConfigLevel.SYSTEM and path.is_file():
                    system_files.append(path)
    if len(system_files) > 1:
        raise _Refused("ambiguous_system_config")
    return list(dict.fromkeys(files))


def _hash_files(hashes: dict[Path, str]) -> dict[Path, str]:
    return {p: hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "missing"
            for p in hashes}


def _scan_includes(files: list[Path]) -> None:
    """Safety net, standard library only: a false positive can only refuse."""
    for path in files:
        try:
            text = path.read_bytes().decode("utf-8-sig", "strict")
        except (OSError, UnicodeDecodeError):
            raise _Refused("config_unreadable") from None
        if any(_INCLUDE_HEADER.match(line) for line in text.splitlines()):
            raise _Refused("config_include_directive")


def _check_configuration(pygit2, repo, state: _State, snapshot: IndexSnapshot
                         ) -> dict[Path, str]:
    enums = _enums(pygit2)
    files = _candidate_config_files(pygit2, state.gitdir)
    _scan_includes([p for p in files if p.is_file()])
    hashes = _hash_files(dict.fromkeys(files, ""))  # "missing" for absent files
    levels = {level.name.lower(): False for level in enums.ConfigLevel}
    values: dict[str, str | None] = {}
    for entry in repo.config:
        name = entry.name.lower()
        if name == "include.path" or name.startswith("includeif."):
            raise _Refused("config_include_directive")
        try:
            level = enums.ConfigLevel(entry.level)
        except ValueError:
            raise _Refused("config_unknown_level", str(entry.level)) from None
        levels[level.name.lower()] = True
        if name.startswith("extensions."):
            raise _Refused("repository_extension", safe_text(name))
        values[name] = entry.value  # later entries win, as in Git
    if levels.get("worktree"):
        raise _Refused("worktree_config")
    local = pygit2.Config(str(state.gitdir / "config"))
    try:
        version = local["core.repositoryformatversion"]
    except KeyError:
        version = "0"
    if version not in ("0", "1"):
        raise _Refused("repository_format_version", safe_text(str(version)))
    _check_values(values)
    state.facts["effective_config"] = {key: values.get(key) for key in _RECORDED}
    state.facts["config_levels_present"] = levels
    return hashes


def _check_values(values: dict[str, str | None]) -> None:
    """Keys that change index writing or the layout, then the compatibility profile."""
    for key in _TRUE_REFUSED:
        if key in values and _git_bool(values[key]):
            raise _Refused("config_not_supported", key)
    for key in _PRESENT_REFUSED:
        if key in values:
            raise _Refused("config_not_supported", key)
    # Allowed only when Git reads them as false; "keep", a hook path or anything else refuses.
    for key in ("core.untrackedcache", "core.fsmonitor"):
        if key in values and not _is_false(values[key]):
            raise _Refused("config_not_supported", key)
    if "index.version" in values and values["index.version"] not in ("2", "4"):
        raise _Refused("config_not_supported", "index.version")
    _check_profile(values)


def _check_profile(values: dict[str, str | None]) -> None:
    """K3: the tested compatibility profile; anything else is untested and refused."""
    if "core.autocrlf" in values:
        autocrlf = values["core.autocrlf"]
        if autocrlf is not None and autocrlf.strip().lower() == "input":
            raise _Refused("untested_configuration", "core.autocrlf")
        try:
            _git_bool(autocrlf)
        except _Refused:
            raise _Refused("untested_configuration", "core.autocrlf") from None
    expected = (("core.ignorecase", True), ("core.filemode", False), ("core.symlinks", False))
    for key, wanted in expected:
        if key not in values or _git_bool(values[key]) is not wanted:
            raise _Refused("untested_configuration", key)
    if "core.longpaths" in values and _git_bool(values["core.longpaths"]):
        raise _Refused("untested_configuration", "core.longpaths")


# --------------------------------------------------------------------------- repository

def _check_repository(pygit2, repo, state: _State):
    enums = _enums(pygit2)
    if repo.is_bare:
        raise _Refused("bare_repository")
    if repo.head_is_unborn:
        raise _Refused("no_head_commit")
    if repo.is_shallow or (state.gitdir / "shallow").exists():
        raise _Refused("shallow_repository")
    target = repo.head.target
    try:
        commit = repo[target]
    except (pygit2.GitError, KeyError, ValueError):
        raise _Refused("head_target_missing") from None
    if not isinstance(commit, pygit2.Commit):
        raise _Refused("head_target_not_commit")
    if repo.state() != enums.RepositoryState.NONE:
        raise _Refused("operation_in_progress", safe_text(str(repo.state())))
    if (state.root / ".gitmodules").exists() or repo.listall_submodules():
        raise _Refused("submodules_present")
    if repo.list_worktrees() or (state.gitdir / "worktrees").exists():
        raise _Refused("linked_worktrees_present")
    if (state.gitdir / "info" / "sparse-checkout").exists():
        raise _Refused("sparse_checkout")
    state.facts.update(commit=str(target), head_detached=bool(repo.head_is_detached))
    return target


def _collect_status(pygit2, repo, state: _State) -> tuple[set[str], set[str]]:
    status = _enums(pygit2).FileStatus
    known = (status.INDEX_NEW | status.INDEX_MODIFIED | status.INDEX_DELETED
             | status.INDEX_RENAMED | status.INDEX_TYPECHANGE | status.WT_NEW
             | status.WT_MODIFIED | status.WT_DELETED | status.WT_TYPECHANGE
             | status.WT_RENAMED | status.CONFLICTED)
    changed: set[str] = set()
    conflicted: set[str] = set()
    for path, flags in _status(repo).items():
        if not isinstance(path, str) or not isinstance(flags, int):
            raise _Refused("status_unreadable")
        if flags & status.IGNORED:
            raise _Refused("status_unexpected_ignored", safe_text(path))
        if flags & status.WT_UNREADABLE:
            raise _Refused("unreadable_file", safe_text(path))
        if flags & ~int(known):
            raise _Refused("status_unknown_bits", hex(flags))
        if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
            raise _Refused("status_absolute_path", safe_text(path))
        _check_path(state.root, path)
        if flags == status.CURRENT:
            continue
        changed.add(path)
        if flags & status.CONFLICTED:
            conflicted.add(path)
    return changed, conflicted


def _check_conflicts(repo, snapshot: IndexSnapshot, from_status: set[str]) -> set[str]:
    """The reader, pygit2's index and the status must agree on conflicts."""
    from_index = set()
    conflicts = repo.index.conflicts
    if conflicts is not None:
        for sides in conflicts:
            paths = {side.path for side in sides if side is not None}
            if len(paths) != 1:
                raise _Refused("conflicts_unreadable")
            from_index |= paths
    if not (set(snapshot.conflict_paths) == from_index == from_status):
        raise _Refused("conflicts_disagree")
    return from_index
