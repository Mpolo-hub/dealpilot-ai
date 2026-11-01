"""O2 strict index reader (spec 003 section 13.3), default suite.

Standard library and the `git` command only: real indexes are produced by Git in temporary
repositories (helpers in git_repo_support.py, with every isolation guard), and malformed
ones are crafted byte by byte. These are reader tests; they are not AC-FC-26, which runs
only with the `formal_checker` marker after its own authorization.
"""
from __future__ import annotations

import pytest

from dealpilot.forecasting import gitindex
from dealpilot.forecasting.gitindex import (
    IndexRejected,
    check_path_text,
    parse_index,
    read_index,
    safe_text,
)
from git_repo_support import (
    OID,
    build_index,
    commit_all,
    entry_bytes,
    git,
    init_repo,
    isolated_env,
    reuc_record,
    simple_entries,
    tree_node,
    write,
)


@pytest.fixture
def repo(tmp_path):
    env = isolated_env(tmp_path)
    path = init_repo(tmp_path / "repo", env)
    write(path, "a.txt", "alpha\n")
    write(path, "dir/b.txt", "beta\n")
    commit_all(path, env)
    return path, env


def _index(path):
    return read_index(path / ".git" / "index")


def _ls_files(path, env) -> set[tuple[str, int, str, int]]:
    """(path, mode, object name, stage) from `git ls-files -s -z`."""
    out = git(path, env, "ls-files", "-s", "-z")
    rows = set()
    for record in filter(None, out.split(b"\0")):
        meta, name = record.split(b"\t", 1)
        mode, oid, stage = meta.split(b" ")
        rows.add((name.decode(), int(mode, 8), oid.decode(), int(stage)))
    return rows


def _rows(snapshot) -> set[tuple[str, int, str, int]]:
    return {(e.path, e.mode, e.oid.hex(), e.stage) for e in snapshot.entries}


def _rejected(data: bytes) -> str:
    with pytest.raises(IndexRejected) as info:
        parse_index(data)
    return info.value.code


# --------------------------------------------------------------------------- Git-produced

def test_o2_index_reader_version_2_matches_git(repo) -> None:
    path, env = repo
    snapshot = _index(path)
    assert snapshot.version == 2
    assert _rows(snapshot) == _ls_files(path, env)
    assert snapshot.extensions == ("TREE",)
    assert snapshot.conflict_paths == ()


def test_o2_index_reader_version_4_matches_git(repo) -> None:
    path, env = repo
    git(path, env, "update-index", "--index-version", "4")
    snapshot = _index(path)
    assert snapshot.version == 4
    assert _rows(snapshot) == _ls_files(path, env)


def test_o2_index_reader_git_writes_v3_only_with_extended_entries(repo) -> None:
    """read-cache.c writes `extended ? 3 : 2`: a requested v3 without extended entries is 2."""
    path, env = repo
    git(path, env, "update-index", "--index-version", "3")
    assert (path / ".git" / "index").read_bytes()[4:8] == b"\0\0\0\2"
    git(path, env, "update-index", "--skip-worktree", "a.txt")
    assert (path / ".git" / "index").read_bytes()[4:8] == b"\0\0\0\3"
    with pytest.raises(IndexRejected) as info:
        _index(path)
    assert info.value.code == "index_skip_worktree"


@pytest.mark.parametrize(("command", "tag", "code"), [
    (("update-index", "--assume-unchanged", "a.txt"), "h a.txt", "index_assume_unchanged"),
    (("update-index", "--skip-worktree", "a.txt"), "S a.txt", "index_skip_worktree"),
])
def test_o2_index_reader_hidden_entries_match_ls_files_v(repo, command, tag, code) -> None:
    path, env = repo
    git(path, env, *command)
    assert tag in git(path, env, "ls-files", "-v").decode().splitlines()
    with pytest.raises(IndexRejected) as info:
        _index(path)
    assert info.value.code == code
    git(path, env, "update-index", "--no-assume-unchanged", "a.txt")
    git(path, env, "update-index", "--no-skip-worktree", "a.txt")
    assert _index(path).version == 2  # no extended entry left, so Git writes version 2


def test_o2_index_reader_intent_to_add_is_refused(repo) -> None:
    path, env = repo
    write(path, "new.txt")
    git(path, env, "add", "-N", "new.txt")
    with pytest.raises(IndexRejected) as info:
        _index(path)
    assert info.value.code == "index_intent_to_add"


def test_o2_index_reader_empty_repository(tmp_path) -> None:
    env = isolated_env(tmp_path)
    path = init_repo(tmp_path / "repo", env)
    git(path, env, "read-tree", "--empty")
    git(path, env, "write-tree")  # writes a 0-entry index with a root TREE, like DealPilot's
    snapshot = _index(path)
    assert snapshot.entries == ()
    assert snapshot.tree == (("", 0, 0, "4b825dc642cb6eb9a060e54bf8d69288fbee4904"),)


def test_o2_index_reader_tree_order_and_object_names_match_git(tmp_path) -> None:
    """Sibling subtrees are ordered by name length, then bytes (cache-tree.c)."""
    env = isolated_env(tmp_path)
    path = init_repo(tmp_path / "repo", env)
    for name in ("b/x.txt", "aa/y.txt", "c/d/e.txt", "ccc/f.txt", "top.txt"):
        write(path, name, name)
    commit_all(path, env)
    git(path, env, "status")
    nodes = _index(path).tree
    assert [n[0] for n in nodes] == ["", "b", "c", "c/d", "aa", "ccc"]
    expected = {"": git(path, env, "rev-parse", "HEAD^{tree}").decode().strip()}
    for line in git(path, env, "ls-tree", "-r", "-d", "HEAD").decode().splitlines():
        meta, name = line.split("\t", 1)
        expected[name] = meta.split()[2]
    assert {n[0]: n[3] for n in nodes} == expected


def test_o2_index_reader_tree_invalidated_nodes(repo) -> None:
    path, env = repo
    write(path, "dir/b.txt", "changed\n")
    git(path, env, "add", "dir/b.txt")
    counts = {n[0]: (n[1], n[3]) for n in _index(path).tree}
    assert counts[""] == (-1, None)
    assert counts["dir"] == (-1, None)


def _conflicted_repo(tmp_path):
    env = isolated_env(tmp_path)
    path = init_repo(tmp_path / "repo", env)
    write(path, "c.txt", "base\n")
    commit_all(path, env)
    git(path, env, "checkout", "-q", "-b", "side")
    write(path, "c.txt", "side\n")
    commit_all(path, env, "side")
    git(path, env, "checkout", "-q", "main")
    write(path, "c.txt", "main\n")
    commit_all(path, env, "main")
    git(path, env, "merge", "-q", "side", check=False)
    return path, env


def test_o2_index_reader_conflict_stages(tmp_path) -> None:
    path, env = _conflicted_repo(tmp_path)
    snapshot = _index(path)
    assert snapshot.conflict_paths == ("c.txt",)
    assert {e.stage for e in snapshot.entries if e.path == "c.txt"} == {1, 2, 3}
    assert _rows(snapshot) == _ls_files(path, env)


def test_o2_index_reader_resolve_undo_matches_git(tmp_path) -> None:
    path, env = _conflicted_repo(tmp_path)
    write(path, "c.txt", "resolved\n")
    git(path, env, "add", "c.txt")
    snapshot = _index(path)
    assert "REUC" in snapshot.extensions
    expected = {}
    for line in git(path, env, "ls-files", "--resolve-undo").decode().splitlines():
        meta, name = line.split("\t", 1)
        mode, oid, stage = meta.split()
        expected.setdefault(name, {})[int(stage)] = (int(mode, 8), oid)
    got = {name: {i + 1: s for i, s in enumerate(stages) if s[0]}
           for name, stages in snapshot.resolve_undo}
    assert got == expected


def test_o2_index_reader_resolve_undo_lifetime(tmp_path) -> None:
    """Empirical check of the plan: REUC survives `commit`, `git checkout` clears it."""
    path, env = _conflicted_repo(tmp_path)
    write(path, "c.txt", "resolved\n")
    git(path, env, "add", "c.txt")
    git(path, env, "commit", "-q", "--no-edit")
    assert "REUC" in _index(path).extensions
    git(path, env, "checkout", "-q", "side")
    assert "REUC" not in _index(path).extensions


def test_o2_index_reader_split_index_is_refused(repo) -> None:
    """Split-index entries carry no name (the shared index holds them), so the entries are
    already refused before the `link` extension is reached."""
    path, env = repo
    git(path, env, "update-index", "--split-index")
    with pytest.raises(IndexRejected) as info:
        _index(path)
    assert info.value.code in ("path_bad_form", "index_unsupported_extension")


@pytest.mark.parametrize(("setup", "code"), [
    ((("config", "core.untrackedCache", "true"), ("update-index", "--untracked-cache"),
      ("status",)), "index_unsupported_extension"),
    ((("-c", "index.recordEndOfIndexEntries=true", "-c", "index.recordOffsetTable=true",
       "update-index", "--force-write-index"),), "index_unsupported_extension"),
    ((("-c", "index.skipHash=true", "update-index", "--force-write-index"),),
     "index_checksum_skipped"),
])
def test_o2_index_reader_refused_extensions(repo, setup, code) -> None:
    path, env = repo
    for command in setup:
        git(path, env, *command)
    with pytest.raises(IndexRejected) as info:
        _index(path)
    assert info.value.code == code


def test_o2_index_reader_sparse_index_is_refused(repo) -> None:
    path, env = repo
    git(path, env, "sparse-checkout", "init", "--cone", "--sparse-index")
    git(path, env, "sparse-checkout", "set", "dir")
    with pytest.raises(IndexRejected):
        _index(path)


# --------------------------------------------------------------------------- file reading

def test_o2_index_reader_missing_file(tmp_path) -> None:
    with pytest.raises(IndexRejected) as info:
        read_index(tmp_path / "index")
    assert info.value.code == "index_missing"


def test_o2_index_reader_changed_during_read(repo, monkeypatch) -> None:
    path, _ = repo
    calls = iter([(1, 1, 1), (2, 2, 2)])
    monkeypatch.setattr(gitindex, "file_stat", lambda p: next(calls))
    with pytest.raises(IndexRejected) as info:
        _index(path)
    assert info.value.code == "index_changed_during_read"


def test_o2_index_reader_too_large(repo, monkeypatch) -> None:
    path, _ = repo
    monkeypatch.setattr(gitindex, "MAX_INDEX_BYTES", 16)
    with pytest.raises(IndexRejected) as info:
        _index(path)
    assert info.value.code == "index_too_large"


def test_o2_index_reader_never_writes(repo) -> None:
    path, _ = repo
    index = path / ".git" / "index"
    before = (index.read_bytes(), index.stat().st_mtime_ns)
    _index(path)
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before
    assert not (path / ".git" / "index.lock").exists()


# --------------------------------------------------------------------------- crafted indexes

def test_o2_index_reader_crafted_baseline_is_valid() -> None:
    for version in (2, 3, 4):
        snapshot = parse_index(build_index(simple_entries([b"a", b"b/c"], version),
                                           version=version))
        assert [e.path for e in snapshot.entries] == ["a", "b/c"]


def test_o2_index_reader_crafted_conflict_stages_accepted() -> None:
    entries = [entry_bytes(b"c", version=2, stage=s) for s in (1, 2, 3)]
    assert parse_index(build_index(entries)).conflict_paths == ("c",)


GOOD = simple_entries([b"a", b"b"])
CRAFTED = {
    "bad signature": build_index(GOOD, signature=b"DIRX"),
    "version 1": build_index(GOOD, version=1),
    "version 5": build_index(GOOD, version=5),
    "count too high": build_index(GOOD, count=3),
    "count too low": build_index(GOOD, count=1),
    "trailing bytes": build_index(GOOD, tail=b"\0" * 8),
    "checksum mismatch": build_index(GOOD, trailer=b"\1" * 20),
    "checksum skipped": build_index(GOOD, trailer=b"\0" * 20),
    "name length": build_index([entry_bytes(b"a", version=2, name_length=2)]),
    "padding not zero": build_index([entry_bytes(b"a", version=2, padding=b"\0x\0\0\0\0\0")]),
    "unsorted": build_index(simple_entries([b"b", b"a"])),
    "duplicate": build_index(simple_entries([b"a", b"a"])),
    "stage mix": build_index([entry_bytes(b"a", version=2),
                              entry_bytes(b"a", version=2, stage=2)]),
    "bad mode": build_index([entry_bytes(b"a", version=2, mode=0o100600)]),
    "gitlink": build_index([entry_bytes(b"a", version=2, mode=0o160000)]),
    "assume valid": build_index([entry_bytes(b"a", version=2, flags=0x8000)]),
    "extended bit in v2": build_index([entry_bytes(b"a", version=2, extended=0)], version=2),
    "extended reserved bit": build_index([entry_bytes(b"a", version=3, extended=0x8000)],
                                         version=3),
    "extended unknown bit": build_index([entry_bytes(b"a", version=3, extended=0x0001)],
                                        version=3),
    "extended all zero": build_index([entry_bytes(b"a", version=3, extended=0)], version=3),
    "v4 strip too long": build_index([entry_bytes(b"a", version=4, strip=3)], version=4),
    "v4 varint overflow": build_index([entry_bytes(b"a", version=4)[:-2] + b"\xff" * 6
                                       + b"\x01a\0"], version=4),
    "unknown optional extension": build_index(GOOD, extensions=[(b"ABCD", b"")]),
    "unknown required extension": build_index(GOOD, extensions=[(b"abcd", b"")]),
    "extension beyond end": build_index(GOOD, tail=b"TREE\0\0\0\x50"),
    "duplicate extension": build_index(GOOD, extensions=[
        (b"REUC", b""), (b"REUC", b"")]),
    "truncated header": b"DIRC\0\0\0\2",
}
for _cut in (14, 40, 70, 90):
    CRAFTED[f"truncated at {_cut}"] = build_index(GOOD)[:_cut] + b"\0" * 20


@pytest.mark.parametrize("case", list(CRAFTED))
def test_o2_index_reader_crafted_refusals(case) -> None:
    _rejected(CRAFTED[case])


BAD_PATHS = [b"", b"..", b".", b"a/../b", b".git/x", b".GIT", b"/a", b"a/", b"a//b",
             b"a\\b", b"a\x01b", b"a\x7fb", b"\xff\xfe", "é".encode()]


@pytest.mark.parametrize("path", BAD_PATHS, ids=[safe_text(p) for p in BAD_PATHS])
def test_o2_index_reader_path_policy(path) -> None:
    assert _rejected(build_index([entry_bytes(path, version=2)])).startswith(
        ("path_", "index_"))


def test_o2_index_reader_path_policy_never_normalizes() -> None:
    nfd = "café"
    with pytest.raises(IndexRejected) as info:
        check_path_text(nfd)
    assert info.value.code == "path_not_nfc"
    assert check_path_text("café") == "café"  # NFC is kept exactly
    with pytest.raises(IndexRejected) as info:
        check_path_text("a\udcff")  # lone surrogate from a tolerant decoding
    assert info.value.code == "path_not_utf8"
    assert safe_text(nfd).isascii() and safe_text(b"\xff").startswith("hex:")


# --------------------------------------------------------------------------- TREE

def _tree(*nodes: bytes, entries: int = 2) -> bytes:
    return build_index(simple_entries([b"a", b"b"][:entries]),
                       extensions=[(b"TREE", b"".join(nodes))])


def test_o2_index_reader_crafted_tree_accepted() -> None:
    data = _tree(tree_node(b"", 2, 2), tree_node(b"z", 1, 0), tree_node(b"aa", 1, 0))
    nodes = parse_index(data).tree
    assert [n[0] for n in nodes] == ["", "z", "aa"]  # shorter name first
    assert nodes[1][3] == OID.hex()


TREE_BAD = {
    "lexicographic order": (tree_node(b"", 2, 2), tree_node(b"aa", 1, 0),
                            tree_node(b"z", 1, 0)),
    "duplicate sibling": (tree_node(b"", 2, 2), tree_node(b"a", 1, 0), tree_node(b"a", 1, 0)),
    "leading zero": (tree_node(b"", b"02", 0, with_oid=True),),
    "plus sign": (tree_node(b"", b"+2", 0, with_oid=True),),
    "double minus": (tree_node(b"", b"--1", 0, with_oid=False),),
    "minus two": (tree_node(b"", b"-2", 0, with_oid=False),),
    "count above entries": (tree_node(b"", 3, 0),),
    "missing object name": (tree_node(b"", 2, 0, with_oid=False),),
    "object name on invalid node": (tree_node(b"", -1, 0, with_oid=True),),
    "too few subtrees": (tree_node(b"", 2, 0), tree_node(b"a", 1, 0)),
    "too many subtrees": (tree_node(b"", 2, 2), tree_node(b"a", 1, 0)),
    "root with a name": (tree_node(b"x", 2, 0),),
    "bad component": (tree_node(b"", 2, 1), tree_node(b"..", 1, 0)),
    "slash in component": (tree_node(b"", 2, 1), tree_node(b"a/b", 1, 0)),
    "empty extension": (b"",),
    "truncated": (tree_node(b"", 2, 0)[:-5],),
}


@pytest.mark.parametrize("case", list(TREE_BAD))
def test_o2_index_reader_crafted_tree_refusals(case) -> None:
    _rejected(_tree(*TREE_BAD[case]))


def test_o2_index_reader_tree_depth_limit(monkeypatch) -> None:
    monkeypatch.setattr(gitindex, "MAX_TREE_DEPTH", 3)
    nodes = [tree_node(b"", -1, 1)] + [tree_node(b"d", -1, 1)] * 3 + [tree_node(b"d", -1, 0)]
    assert _rejected(_tree(*nodes)) == "tree_too_deep"


# --------------------------------------------------------------------------- REUC

def _reuc(*records: bytes) -> bytes:
    return build_index(GOOD, extensions=[(b"REUC", b"".join(records))])


def test_o2_index_reader_crafted_reuc_accepted() -> None:
    data = _reuc(reuc_record(b"a", (b"100644", b"100644", b"0")),
                 reuc_record(b"b", (b"0", b"100755", b"120000")))
    records = dict(parse_index(data).resolve_undo)
    assert records["a"] == ((0o100644, OID.hex()), (0o100644, OID.hex()), (0, None))
    assert parse_index(_reuc()).resolve_undo == ()  # an empty REUC is well formed


REUC_BAD = {
    "leading zero mode": (reuc_record(b"a", (b"0100644", b"0", b"0")),),
    "unknown mode": (reuc_record(b"a", (b"100600", b"0", b"0")),),
    "not octal": (reuc_record(b"a", (b"100648", b"0", b"0")),),
    "all stages missing": (reuc_record(b"a", (b"0", b"0", b"0")),),
    "missing object name": (reuc_record(b"a", (b"100644", b"0", b"0"), oids=0),),
    "extra object name": (reuc_record(b"a", (b"100644", b"0", b"0"), oids=2),),
    "unsorted": (reuc_record(b"b", (b"100644", b"0", b"0")),
                 reuc_record(b"a", (b"100644", b"0", b"0"))),
    "duplicate": (reuc_record(b"a", (b"100644", b"0", b"0")),) * 2,
    "bad path": (reuc_record(b"../a", (b"100644", b"0", b"0")),),
    "truncated": (reuc_record(b"a", (b"100644", b"0", b"0"))[:-3],),
}


@pytest.mark.parametrize("case", list(REUC_BAD))
def test_o2_index_reader_crafted_reuc_refusals(case) -> None:
    _rejected(_reuc(*REUC_BAD[case]))
