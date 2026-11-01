"""O2 clean-tree controller (spec 003 section 13.3).

Two groups:
- `test_o2_controller_*` (default suite): phase A refusals that happen before pygit2 is
  imported, the refusal shape, configuration value parsing, and the isolation of pygit2
  from the application. They need no new dependency. Tests that reach the root check need
  Windows (profile `o2-windows-v1`) and are skipped elsewhere, with a reason.
- `test_ac_fc_26_*` (marker `formal_checker`): AC-FC-26, the comparison with Git. They need
  pygit2 (the `formal` extra) and run only with `pytest -m formal_checker` while
  DEALPILOT_RUN_AC_FC_26 holds the exact value in git_repo_support.py, after their own
  authorization (O2 gate 6). Without that value conftest.py removes them from every run,
  whatever -m says. Without pygit2 they fail; they never skip silently.

Every repository lives in a temporary folder outside the project, and every `git` call uses
the isolated environment of git_repo_support.py (guards C7 to C9).
"""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dealpilot.forecasting import cleantree
from dealpilot.forecasting.cleantree import CLEAN, DIRTY, REFUSED, check_clean_tree
from git_repo_support import (
    AC_FC_26_VALUE,
    AC_FC_26_VARIABLE,
    PROJECT_ROOT,
    ac_fc_26_authorized,
    build_index,
    commit_all,
    entry_bytes,
    git,
    index_sha256,
    init_repo,
    isolated_env,
    porcelain_paths,
    write,
)

ENV_FOLDERS = ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "APPDATA", "LOCALAPPDATA",
               "PROGRAMDATA")
# The controller refuses every platform but Windows before reading the repository.
windows_only = pytest.mark.skipif(os.name != "nt",
                                  reason="profile o2-windows-v1 covers Windows only (13.3)")


@pytest.fixture
def env(tmp_path, monkeypatch) -> dict[str, str]:
    """Isolated environment for `git`, mirrored into os.environ for the controller."""
    git_env = isolated_env(tmp_path)
    for name in list(os.environ):
        if name.upper().startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)
    for name in (*ENV_FOLDERS, "HOMEDRIVE", "HOMEPATH"):
        monkeypatch.setenv(name, git_env[name])
    return git_env


@pytest.fixture
def repo(tmp_path, env) -> Path:
    path = init_repo(tmp_path / "repo", env)
    write(path, "a.txt", "alpha\n")
    write(path, "dir/b.txt", "beta\n")
    commit_all(path, env)
    return path


def no_checker(monkeypatch) -> None:
    def missing():
        raise ImportError("pygit2 is not installed")

    monkeypatch.setattr(cleantree, "_import_pygit2", missing)


def assert_refused(result, code: str | None = None) -> None:
    assert result.outcome == REFUSED and not result.clean
    assert len(result.reasons) == 1 and result.changed_paths == ()
    if code is not None:
        assert result.reasons[0].split(":")[0] == code, result.reasons


# --------------------------------------------------------------------------- default suite

def test_o2_controller_pygit2_never_imported_by_the_application() -> None:
    script = ("import sys; import dealpilot.api.main, dealpilot.ai, dealpilot.forecasting, "
              "dealpilot.forecasting.cleantree, dealpilot.forecasting.gitindex; "
              "print('pygit2' in sys.modules)")
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                            check=False, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


@windows_only
def test_o2_controller_reaches_the_checker_import(repo, monkeypatch) -> None:
    """Every phase A check before the import passes on a normal repository."""
    no_checker(monkeypatch)
    result = check_clean_tree(repo)
    assert_refused(result, "checker_unavailable")
    assert (result.index_version, result.index_extensions) == (2, ("TREE",))
    assert result.provenance()["clean_tree"] is False


@pytest.mark.parametrize("name", ["GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                                  "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM",
                                  "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_KEY_0"])
def test_o2_controller_forbidden_environment(repo, monkeypatch, name) -> None:
    no_checker(monkeypatch)
    monkeypatch.setenv(name, "")
    assert_refused(check_clean_tree(repo), "forbidden_environment_variable")


@pytest.mark.parametrize(("variable", "relative"), [
    ("APPDATA", "git/config"), ("APPDATA", "git/ignore"), ("LOCALAPPDATA", "git/attributes"),
    ("PROGRAMDATA", "Git/config")])
def test_o2_controller_libgit2_only_files(repo, env, monkeypatch, variable, relative) -> None:
    no_checker(monkeypatch)
    write(Path(env[variable]), relative, "")
    assert_refused(check_clean_tree(repo), "libgit2_only_config_file")


def test_o2_controller_ambiguous_global_config(repo, tmp_path, monkeypatch) -> None:
    no_checker(monkeypatch)
    for name in ("one", "two"):
        write(tmp_path / name, ".gitconfig", "")
    monkeypatch.setenv("HOME", str(tmp_path / "one"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "two"))
    assert_refused(check_clean_tree(repo), "ambiguous_global_config")


@windows_only
def test_o2_controller_root_checks(repo, tmp_path, monkeypatch) -> None:
    no_checker(monkeypatch)
    assert_refused(check_clean_tree(repo / "dir"), "no_repository_at_root")  # parent repo
    plain = tmp_path / "plain"
    write(plain, ".git", "gitdir: elsewhere\n")  # a .git file: linked worktree or submodule
    assert_refused(check_clean_tree(plain), "no_repository_at_root")
    write(repo, ".git/commondir", "../other\n")
    assert_refused(check_clean_tree(repo), "linked_worktree")


@windows_only
@pytest.mark.parametrize("lock", ["index.lock", "HEAD.lock", "config.lock", "other.lock",
                                  "refs/heads/topic.lock", "logs/refs/heads/main.lock",
                                  "objects/info/commit-graph.lock",
                                  "objects/pack/multi-pack-index.lock"])
def test_o2_controller_locks(repo, monkeypatch, lock) -> None:
    no_checker(monkeypatch)
    write(repo, f".git/{lock}", "")
    assert_refused(check_clean_tree(repo), "git_lock_present")


@windows_only
def test_o2_controller_index_problems(tmp_path, env, monkeypatch) -> None:
    no_checker(monkeypatch)
    path = init_repo(tmp_path / "fresh", env)
    assert_refused(check_clean_tree(path), "index_missing")
    write(path, ".git/index", b"DIRC garbage")
    assert_refused(check_clean_tree(path), "index_truncated")


@windows_only
def test_o2_controller_symlink_entry(repo, monkeypatch) -> None:
    """K4: a symlink entry with core.symlinks=false is outside the tested profile."""
    no_checker(monkeypatch)
    (repo / ".git" / "index").write_bytes(build_index(
        [entry_bytes(b"link", version=2, mode=0o120000)]))
    assert_refused(check_clean_tree(repo), "symlink_entry")


@windows_only
def test_o2_controller_non_ascii_path(repo, env, monkeypatch) -> None:
    no_checker(monkeypatch)
    write(repo, "café.txt")
    git(repo, env, "add", "café.txt")
    result = check_clean_tree(repo)
    assert_refused(result, "non_ascii_path")
    assert result.reasons[0].isascii()


@windows_only
def test_o2_controller_path_too_long(repo, monkeypatch) -> None:
    no_checker(monkeypatch)
    name = ("d" * 200 + "/" + "f" * 100).encode()
    (repo / ".git" / "index").write_bytes(build_index([entry_bytes(name, version=2)]))
    assert_refused(check_clean_tree(repo), "path_too_long")


@windows_only
def test_o2_controller_unexpected_error_is_refused(repo, monkeypatch) -> None:
    def broken(path):
        raise RuntimeError("boom")

    monkeypatch.setattr(cleantree, "read_index", broken)
    assert_refused(check_clean_tree(repo), "unexpected_error")


@pytest.mark.skipif(os.name == "nt", reason="checks the refusal on other platforms")
def test_o2_controller_other_platforms_refused(repo, monkeypatch) -> None:
    no_checker(monkeypatch)
    assert_refused(check_clean_tree(repo), "unsupported_platform")


def _commit_special_entry(repo, env, path: str, mode: str) -> None:
    if mode == "120000":
        oid = git(repo, env, "hash-object", "-w", "--stdin", stdin=b"target")
    else:
        oid = git(repo, env, "rev-parse", "HEAD")
    git(repo, env, "update-index", "--add", "--cacheinfo",
        f"{mode},{oid.decode().strip()},{path}")
    git(repo, env, "commit", "-q", "-m", "special entry")


@windows_only
@pytest.mark.parametrize(("path", "mode", "git_code", "code"), [
    ("link", "120000", " M", "symlink_entry"),  # core.symlinks=false: Git compares content
    ("sub", "160000", " T", "index_gitlink_entry")])
def test_o2_controller_type_change_refused(repo, env, monkeypatch, path, mode, git_code,
                                           code) -> None:
    """AC-FC-26 type changes (13.3, K4): in this profile only a symlink or a gitlink entry
    can change type, and both are refused before pygit2 loads, so never CLEAN."""
    no_checker(monkeypatch)
    _commit_special_entry(repo, env, path, mode)
    write(repo, path, "now a regular file\n")
    status = git(repo, env, "--no-optional-locks", "status", "--porcelain=v1").decode()
    assert f"{git_code} {path}" in status.splitlines()
    result = check_clean_tree(repo)
    assert_refused(result, code)
    assert result.outcome != CLEAN


PROFILE = {"core.ignorecase": "true", "core.filemode": "false", "core.symlinks": "false"}


@pytest.mark.parametrize("values", [
    {"core.ignorecase": "TRUE", "core.filemode": "False", "core.symlinks": "off"},
    {"core.autocrlf": "True"}, {"core.autocrlf": "FALSE"}, {"core.autocrlf": None},
    {"core.untrackedcache": "False"}, {"core.untrackedcache": "0"},
    {"core.fsmonitor": "No"}, {"core.fsmonitor": ""}, {"core.fsmonitor": "OFF"}])
def test_o2_controller_boolean_values_any_case(values) -> None:
    cleantree._check_values({**PROFILE, **values})


@pytest.mark.parametrize(("values", "code"), [
    ({"core.autocrlf": "Input"}, "untested_configuration"),
    ({"core.autocrlf": "maybe"}, "untested_configuration"),
    ({"core.ignorecase": "FALSE"}, "untested_configuration"),
    ({"core.ignorecase": "sometimes"}, "ambiguous_config_value"),
    ({"core.untrackedcache": "keep"}, "config_not_supported"),
    ({"core.untrackedcache": "TRUE"}, "config_not_supported"),
    ({"core.untrackedcache": None}, "config_not_supported"),
    ({"core.fsmonitor": "Yes"}, "config_not_supported"),
    ({"core.fsmonitor": "C:/hooks/fsmonitor.exe"}, "config_not_supported"),
    ({"core.splitindex": "True"}, "config_not_supported")])
def test_o2_controller_boolean_values_fail_closed(values, code) -> None:
    with pytest.raises(cleantree._Refused) as refused:
        cleantree._check_values({**PROFILE, **values})
    assert refused.value.reason.split(":")[0] == code


def test_o2_controller_ac_fc_26_guard() -> None:
    """The default suite never runs with the AC-FC-26 authorization value (conftest.py)."""
    assert AC_FC_26_VARIABLE == "DEALPILOT_RUN_AC_FC_26"
    assert os.environ.get(AC_FC_26_VARIABLE) != AC_FC_26_VALUE
    assert not ac_fc_26_authorized()


# --------------------------------------------------------------------------- AC-FC-26

@pytest.fixture
def pygit2_isolated(tmp_path, env):
    """pygit2 with every configuration search path in the temporary folder, restored after."""
    if not ac_fc_26_authorized():  # second barrier behind conftest.py, before any import
        pytest.fail(f"AC-FC-26 needs {AC_FC_26_VARIABLE}={AC_FC_26_VALUE} (O2 gate 6)")
    try:
        pygit2 = importlib.import_module("pygit2")
    except ImportError:
        pytest.fail("AC-FC-26 needs pygit2 (the `formal` extra); install it only after the "
                    "dependency gates are approved")
    levels = pygit2.enums.ConfigLevel
    targets = {levels.SYSTEM: tmp_path / "env" / "system", levels.GLOBAL: Path(env["HOME"]),
               levels.XDG: Path(env["XDG_CONFIG_HOME"]) / "git",
               levels.PROGRAMDATA: Path(env["PROGRAMDATA"]) / "Git"}
    saved = {level: pygit2.settings.search_path[level] for level in targets}
    for level, folder in targets.items():
        folder.mkdir(parents=True, exist_ok=True)
        pygit2.settings.search_path[level] = str(folder)
    yield pygit2
    for level, value in saved.items():
        pygit2.settings.search_path[level] = value


def checked(path: Path):
    """The controller, with the index measured just before and just after (no git between)."""
    before = index_sha256(path)
    result = check_clean_tree(path)
    assert index_sha256(path) == before
    assert not (path / ".git" / "index.lock").exists()
    return result


def assert_matches_git(path: Path, env: dict[str, str], result) -> None:
    expected = porcelain_paths(path, env)
    assert result.outcome == (DIRTY if expected else CLEAN), result.reasons
    assert set(result.changed_paths) == expected


def _modified(repo, env):
    write(repo, "a.txt", "changed\n")


def _deleted(repo, env):
    (repo / "a.txt").unlink()


def _staged_rename(repo, env):
    git(repo, env, "mv", "a.txt", "renamed.txt")


def _disk_rename(repo, env):
    (repo / "a.txt").rename(repo / "renamed.txt")


def _staged_change(repo, env):
    write(repo, "a.txt", "staged\n")
    git(repo, env, "add", "a.txt")


def _staged_new(repo, env):
    write(repo, "new.txt")
    git(repo, env, "add", "new.txt")


def _untracked(repo, env):
    write(repo, "deep/er/new.txt")


def _ignored_only(repo, env):
    write(repo, ".gitignore", "*.log\n")
    commit_all(repo, env)
    write(repo, "debug.log")


def _env_negation(repo, env):
    write(repo, ".gitignore", ".env\n.env.*\n!.env.example\n")
    commit_all(repo, env)
    write(repo, ".env.example")
    write(repo, ".env.local")


def _dealpilot_negation(repo, env):
    """The project's own rules: `data/` ignored, `!backend/src/dealpilot/data/` re-included."""
    write(repo, ".gitignore", (PROJECT_ROOT / ".gitignore").read_bytes())
    commit_all(repo, env)
    write(repo, "data/raw/orders.parquet")
    write(repo, "backend/src/dealpilot/data/generate.py")
    write(repo, "backend/src/dealpilot/data/__pycache__/x.pyc")


def _case_rename(repo, env):
    git(repo, env, "mv", "a.txt", "A.txt")


def _disk_case_rename(repo, env):
    """Case-only rename on disk, not through Git, with core.ignorecase=true."""
    (repo / "a.txt").rename(repo / "A.txt")


def _file_to_directory(repo, env):
    (repo / "a.txt").unlink()
    write(repo, "a.txt/inner.txt")


SCENARIOS = {f.__name__.strip("_"): f for f in (
    _modified, _deleted, _staged_rename, _disk_rename, _staged_change, _staged_new,
    _untracked, _ignored_only, _env_negation, _dealpilot_negation, _case_rename,
    _disk_case_rename, _file_to_directory)}


@pytest.mark.formal_checker
def test_ac_fc_26_clean_repository(repo, env, pygit2_isolated) -> None:
    result = checked(repo)
    assert_matches_git(repo, env, result)
    assert result.outcome == CLEAN and result.commit and result.head_detached is False
    assert result.checker_version and result.libgit2_version


@pytest.mark.formal_checker
@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_ac_fc_26_matches_git_status(repo, env, pygit2_isolated, scenario) -> None:
    SCENARIOS[scenario](repo, env)
    assert_matches_git(repo, env, checked(repo))


@pytest.mark.formal_checker
@pytest.mark.parametrize("autocrlf", ["true", "false"])
@pytest.mark.parametrize("change", ["crlf_rewrite", "touch", "bat_file"])
def test_ac_fc_26_line_endings(tmp_path, env, pygit2_isolated, autocrlf, change) -> None:
    repo = init_repo(tmp_path / "eol", env, autocrlf=autocrlf)
    write(repo, ".gitattributes", (PROJECT_ROOT / ".gitattributes").read_bytes())
    write(repo, "text.txt", b"one\ntwo\n")
    write(repo, "run.bat", b"echo one\r\necho two\r\n")
    commit_all(repo, env)
    if change == "crlf_rewrite":
        write(repo, "text.txt", b"one\r\ntwo\r\n")
    elif change == "touch":
        os.utime(repo / "text.txt", None)
    else:
        write(repo, "run.bat", b"echo one\necho two\n")
    assert_matches_git(repo, env, checked(repo))


@pytest.mark.formal_checker
def test_ac_fc_26_conflict_without_operation_is_dirty(repo, env, pygit2_isolated) -> None:
    write(repo, "a.txt", "stashed\n")
    git(repo, env, "stash")
    write(repo, "a.txt", "local\n")
    commit_all(repo, env, "local")
    git(repo, env, "stash", "pop", check=False)
    result = checked(repo)
    assert result.outcome == DIRTY and result.conflict_paths == ("a.txt",)
    assert_matches_git(repo, env, result)


@pytest.mark.formal_checker
def test_ac_fc_26_detached_head_is_accepted(repo, env, pygit2_isolated) -> None:
    git(repo, env, "checkout", "-q", "--detach")
    result = checked(repo)
    assert result.outcome == CLEAN and result.head_detached is True


def _branch_with_conflict(repo, env):
    git(repo, env, "checkout", "-q", "-b", "side")
    write(repo, "a.txt", "side\n")
    commit_all(repo, env, "side")
    git(repo, env, "checkout", "-q", "main")
    write(repo, "a.txt", "main\n")
    commit_all(repo, env, "main")


def _merge_conflict(repo, env):
    _branch_with_conflict(repo, env)
    git(repo, env, "merge", "-q", "side", check=False)


def _merge_no_commit(repo, env):
    git(repo, env, "checkout", "-q", "-b", "side")
    write(repo, "other.txt")
    commit_all(repo, env, "side")
    git(repo, env, "checkout", "-q", "main")
    git(repo, env, "merge", "-q", "--no-ff", "--no-commit", "side")


def _cherry_pick_conflict(repo, env):
    _branch_with_conflict(repo, env)
    git(repo, env, "cherry-pick", "side", check=False)


def _revert_conflict(repo, env):
    write(repo, "a.txt", "second\n")
    commit_all(repo, env, "second")
    write(repo, "a.txt", "third\n")
    commit_all(repo, env, "third")
    git(repo, env, "revert", "--no-edit", "HEAD~1", check=False)


def _rebase_edit(repo, env):
    write(repo, "a.txt", "second\n")
    commit_all(repo, env, "second")
    editor = repo.parent / "editor.py"
    editor.write_text("import sys, pathlib\np = pathlib.Path(sys.argv[1])\n"
                      "p.write_text(p.read_text().replace('pick', 'edit', 1))\n")
    env = dict(env, GIT_SEQUENCE_EDITOR=f'"{sys.executable}" "{editor}"')
    git(repo, env, "rebase", "-i", "HEAD~1")


def _bisect(repo, env):
    git(repo, env, "bisect", "start")


def _local_include(repo, env):
    git(repo, env, "config", "--local", "include.path", "missing.inc")


def _global_include_if(repo, env):
    write(Path(env["HOME"]), ".gitconfig",
          '[IncludeIf "hasconfig:remote.*.url:https://example.invalid/**"]\n\tpath = x\n')


def _filemode_true(repo, env):
    git(repo, env, "config", "--local", "core.filemode", "true")


def _autocrlf_input(repo, env):
    git(repo, env, "config", "--local", "core.autocrlf", "input")


def _symlink_entry(repo, env):
    blob = git(repo, env, "hash-object", "-w", "--stdin", stdin=b"target").decode().strip()
    git(repo, env, "update-index", "--add", "--cacheinfo", f"120000,{blob},link")


def _gitlink_entry(repo, env):
    head = git(repo, env, "rev-parse", "HEAD").decode().strip()
    git(repo, env, "update-index", "--add", "--cacheinfo", f"160000,{head},sub")


def _sparse(repo, env):
    git(repo, env, "sparse-checkout", "set", "dir")


def _main_with_worktree(repo, env):
    git(repo, env, "worktree", "add", "-q", str(repo.parent / "wt"), "-b", "wt")


def _missing_head_commit(repo, env):
    (repo / ".git" / "HEAD").write_text("0123456789abcdef0123456789abcdef01234567\n")


def _head_on_tree(repo, env):
    tree = git(repo, env, "rev-parse", "HEAD^{tree}").decode().strip()
    (repo / ".git" / "HEAD").write_text(tree + "\n")


REFUSALS = {f.__name__.strip("_"): f for f in (
    _merge_conflict, _merge_no_commit, _cherry_pick_conflict, _revert_conflict, _rebase_edit,
    _bisect, _local_include, _global_include_if, _filemode_true, _autocrlf_input,
    _symlink_entry, _gitlink_entry, _sparse, _main_with_worktree, _missing_head_commit,
    _head_on_tree)}


@pytest.mark.formal_checker
@pytest.mark.parametrize("scenario", list(REFUSALS))
def test_ac_fc_26_refusals(repo, env, pygit2_isolated, scenario) -> None:
    REFUSALS[scenario](repo, env)
    assert_refused(checked(repo))


@pytest.mark.formal_checker
@pytest.mark.parametrize(("path", "mode", "code"), [
    ("link", "120000", "symlink_entry"), ("sub", "160000", "index_gitlink_entry")])
def test_ac_fc_26_type_change_refused(repo, env, pygit2_isolated, path, mode, code) -> None:
    """Type changes are covered by refusal (13.3, K4), with the checker installed."""
    _commit_special_entry(repo, env, path, mode)
    write(repo, path, "now a regular file\n")
    assert_refused(checked(repo), code)


@pytest.mark.formal_checker
@pytest.mark.parametrize("level", ["xdg", "system"])
def test_ac_fc_26_include_if_at_other_levels(repo, env, pygit2_isolated, level) -> None:
    if level == "xdg":
        target = Path(env["XDG_CONFIG_HOME"]) / "git" / "config"
    else:
        target = repo.parent / "env" / "system" / "gitconfig"  # pygit2_isolated SYSTEM
    write(target.parent, target.name, '[includeIf "gitdir:~/elsewhere/"]\n\tpath = x.inc\n')
    assert_refused(checked(repo), "config_include_directive")


@pytest.mark.formal_checker
def test_ac_fc_26_long_untracked_path(repo, env, pygit2_isolated) -> None:
    """An untracked path longer than 259 characters is never CLEAN (13.3 path policy)."""
    relative = "d" * 120 + "/" + "f" * 120 + ".txt"
    assert len(str(repo / relative)) > cleantree.MAX_PATH_CHARS
    target = Path("\\\\?\\" + str(repo / relative))  # works without LongPathsEnabled
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x\n")
    result = checked(repo)
    assert_refused(result)
    assert result.outcome != CLEAN


@pytest.mark.formal_checker
def test_ac_fc_26_repository_shapes(tmp_path, env, pygit2_isolated) -> None:
    bare = tmp_path / "bare"
    git(tmp_path, env, "init", "-q", "--bare", str(bare))
    assert_refused(check_clean_tree(bare))
    unborn = init_repo(tmp_path / "unborn", env)
    write(unborn, "a.txt")
    git(unborn, env, "add", "a.txt")
    assert_refused(checked(unborn), "no_head_commit")
    source = init_repo(tmp_path / "source", env)
    for i in range(2):
        write(source, "a.txt", str(i))
        commit_all(source, env, str(i))
    shallow = tmp_path / "shallow"
    git(tmp_path, env, "clone", "-q", "--depth", "1", source.as_uri(), str(shallow))
    for key, value in (("core.ignorecase", "true"), ("core.filemode", "false"),
                       ("core.symlinks", "false")):
        git(shallow, env, "config", "--local", key, value)
    assert_refused(checked(shallow), "shallow_repository")
    for option in ("--object-format=sha256", "--ref-format=reftable"):
        other = tmp_path / option.strip("-").replace("=", "_")
        git(tmp_path, env, "init", "-q", option, str(other), check=False)
        if (other / ".git").is_dir():
            write(other, "a.txt")
            git(other, env, "add", "a.txt", check=False)
            assert_refused(check_clean_tree(other))


@pytest.mark.formal_checker
def test_ac_fc_26_linked_worktree_side(repo, env, pygit2_isolated) -> None:
    worktree = repo.parent / "wt"
    git(repo, env, "worktree", "add", "-q", str(worktree), "-b", "wt")
    assert_refused(check_clean_tree(worktree))


@pytest.mark.formal_checker
def test_ac_fc_26_submodule(repo, env, pygit2_isolated, tmp_path) -> None:
    other = init_repo(tmp_path / "other", env)
    write(other, "x.txt")
    commit_all(other, env)
    git(repo, env, "-c", "protocol.file.allow=always", "submodule", "add", "-q",
        other.as_uri(), "sub")
    commit_all(repo, env, "submodule")
    assert_refused(check_clean_tree(repo))


@pytest.mark.formal_checker
def test_ac_fc_26_untracked_non_ascii_path(repo, env, pygit2_isolated) -> None:
    write(repo, "café.txt")  # not allowed until parity is established (13.3)
    assert_refused(checked(repo), "non_ascii_path")


@pytest.mark.formal_checker
def test_ac_fc_26_unreadable_file(repo, env, pygit2_isolated) -> None:
    """Platform dependent: never CLEAN when a file can't be read."""
    target = repo / "a.txt"
    write(repo, "a.txt", "changed\n")
    icacls = shutil.which("icacls")
    if icacls is None:
        pytest.skip("icacls is not available on this machine")
    deny = subprocess.run([icacls, str(target), "/deny", "*S-1-1-0:(R)"],
                          capture_output=True, check=False)
    if deny.returncode != 0:
        pytest.skip("read permission can't be removed on this machine")
    try:
        result = check_clean_tree(repo)
    finally:
        subprocess.run([icacls, str(target), "/remove:d", "*S-1-1-0"], capture_output=True,
                       check=False)
    assert result.outcome != CLEAN


def _rewrite_index(repo, env):
    data = (repo / ".git" / "index").read_bytes()
    (repo / ".git" / "index").write_bytes(data)  # same bytes, new modification time


CONCURRENT = {
    "lock_created": (lambda repo, env: write(repo, ".git/index.lock", ""), "git_lock_present"),
    "ref_lock_created": (lambda repo, env: write(repo, ".git/refs/heads/x.lock", ""),
                         "git_lock_present"),
    "head_moved": (lambda repo, env: git(repo, env, "commit", "-q", "--allow-empty", "-m", "x"),
                   None),
    "merge_head_created": (lambda repo, env: write(
        repo, ".git/MERGE_HEAD", git(repo, env, "rev-parse", "HEAD")),
        "operation_started_during_check"),
    "index_rewritten": (_rewrite_index, "index_changed_during_check"),
    "local_config_changed": (lambda repo, env: git(
        repo, env, "config", "--local", "user.name", "Changed"),
        "configuration_changed_during_check"),
    "global_config_created": (lambda repo, env: write(
        Path(env["HOME"]), ".gitconfig", "[user]\n\tname = Created\n"),
        "configuration_changed_during_check"),
}


@pytest.mark.formal_checker
@pytest.mark.parametrize("case", list(CONCURRENT))
def test_ac_fc_26_concurrent_changes(repo, env, pygit2_isolated, monkeypatch, case) -> None:
    action, code = CONCURRENT[case]
    real_status = cleantree._status

    def status_with_change(repository):
        action(repo, env)
        return real_status(repository)

    monkeypatch.setattr(cleantree, "_status", status_with_change)
    assert_refused(check_clean_tree(repo), code)


@pytest.mark.formal_checker
def test_ac_fc_26_index_restored_is_a_known_limit(repo, env, pygit2_isolated, monkeypatch
                                                  ) -> None:
    """Section 13.3 limit: an index changed and put back exactly is not detected."""
    index = repo / ".git" / "index"
    real_status = cleantree._status

    def status_with_restore(repository):
        data, times = index.read_bytes(), (index.stat().st_atime_ns, index.stat().st_mtime_ns)
        index.write_bytes(data + b"")
        os.utime(index, ns=times)
        return real_status(repository)

    monkeypatch.setattr(cleantree, "_status", status_with_restore)
    assert check_clean_tree(repo).outcome == CLEAN
