"""Shared helpers for the O2 clean-tree tests (spec 003 section 13.3). Not a test module.

Safety guards (C7 to C9): every `git` call runs as `git -C <temporary repository>` with an
environment where every inherited GIT_* variable is removed, GIT_CEILING_DIRECTORIES stops
discovery at the temporary folder, system configuration is off and every home or config
folder points into the temporary folder. Nothing here touches the DealPilot repository.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OID = bytes(range(20))  # any 20 bytes; crafted indexes never need real objects

# AC-FC-26 guard (spec 003 section 13.3): `formal_checker` tests run only when this variable
# holds exactly this value. Set it only after O2 gate 6 (running AC-FC-26) is approved.
AC_FC_26_VARIABLE = "DEALPILOT_RUN_AC_FC_26"
AC_FC_26_VALUE = "o2-gate-6-approved"


def ac_fc_26_authorized() -> bool:
    return os.environ.get(AC_FC_26_VARIABLE) == AC_FC_26_VALUE


def git_executable() -> str:
    git = shutil.which("git")
    if git is None:
        pytest.fail("git is required for the O2 clean-tree tests")
    return git


def assert_outside_project(path: Path) -> None:
    resolved = Path(path).resolve()
    if resolved == PROJECT_ROOT or PROJECT_ROOT in resolved.parents:
        pytest.fail("temporary folders must be outside the DealPilot repository")


def isolated_env(base: Path) -> dict[str, str]:
    """Environment for `git` subprocesses: no inherited GIT_*, all config folders private."""
    assert_outside_project(base)
    folders = {name: base / "env" / name.lower() for name in (
        "HOME", "USERPROFILE", "XDG_CONFIG_HOME", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA")}
    for folder in folders.values():
        folder.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update({name: str(folder) for name, folder in folders.items()})
    drive, rest = os.path.splitdrive(str(folders["HOME"]))
    env.update(HOMEDRIVE=drive, HOMEPATH=rest, GIT_CONFIG_NOSYSTEM="1",
               GIT_CEILING_DIRECTORIES=str(base), GIT_TERMINAL_PROMPT="0")
    return env


def git(repo: Path, env: dict[str, str], *args: str, check: bool = True,
        stdin: bytes | None = None) -> bytes:
    assert_outside_project(repo)
    result = subprocess.run([git_executable(), "-C", str(repo), *args], env=env, input=stdin,
                            capture_output=True, check=False)
    if check and result.returncode != 0:
        pytest.fail(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace')}")
    return result.stdout


def init_repo(repo: Path, env: dict[str, str], *, autocrlf: str = "false") -> Path:
    """A repository with the O2 profile settings fixed locally (section 13.3)."""
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, env, "init", "-q", "-b", "main")
    for key, value in (("user.name", "O2 Test"), ("user.email", "o2@example.invalid"),
                       ("core.autocrlf", autocrlf), ("core.ignorecase", "true"),
                       ("core.filemode", "false"), ("core.symlinks", "false"),
                       ("commit.gpgsign", "false")):
        git(repo, env, "config", "--local", key, value)
    return repo


def write(repo: Path, relative: str, content: bytes | str = b"x\n") -> Path:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return path


def commit_all(repo: Path, env: dict[str, str], message: str = "commit") -> None:
    git(repo, env, "add", "-A")
    git(repo, env, "commit", "-q", "-m", message)


def porcelain_paths(repo: Path, env: dict[str, str]) -> set[str]:
    """Paths of `git status --porcelain=v1 --untracked-files=all -z`, renames as two paths."""
    out = git(repo, env, "--no-optional-locks", "status", "--porcelain=v1",
              "--untracked-files=all", "-z")
    fields = out.split(b"\0")
    paths: set[str] = set()
    i = 0
    while i < len(fields):
        record = fields[i]
        i += 1
        if not record:
            continue
        xy, path = record[:2], record[3:]
        paths.add(path.decode("utf-8"))
        if xy[:1] in (b"R", b"C") or xy[1:2] in (b"R", b"C"):
            paths.add(fields[i].decode("utf-8"))  # the original path follows
            i += 1
    return paths


def index_sha256(repo: Path) -> str:
    return hashlib.sha256((repo / ".git" / "index").read_bytes()).hexdigest()


# --------------------------------------------------------------------------- crafted indexes

def entry_bytes(path: bytes, *, version: int, previous: bytes = b"", mode: int = 0o100644,
                stage: int = 0, flags: int = 0, extended: int | None = None,
                name_length: int | None = None, padding: bytes | None = None,
                strip: int | None = None) -> bytes:
    """One index entry. Fields not under test are fixed so the bytes are deterministic."""
    length = len(path) if name_length is None else name_length
    all_flags = flags | (stage << 12) | min(length, 0xFFF) | (0x4000 if extended is not None
                                                              else 0)
    head = struct.pack(">10I", 0, 0, 0, 0, 0, 0, mode, 0, 0, 0) + OID
    head += struct.pack(">H", all_flags)
    if extended is not None:
        head += struct.pack(">H", extended)
    if version == 4:
        if strip is None:
            common = 0
            while (common < min(len(previous), len(path))
                   and previous[common] == path[common]):
                common += 1
            strip = len(previous) - common
            suffix = path[common:]
        else:
            suffix = path
        return head + varint(strip) + suffix + b"\0"
    size = (len(head) + len(path) + 8) & ~7
    pad = padding if padding is not None else b"\0" * (size - len(head) - len(path))
    return head + path + pad


def varint(value: int) -> bytes:
    """Git's offset varint (OFS_DELTA encoding)."""
    out = [value & 0x7F]
    value >>= 7
    while value:
        value -= 1
        out.insert(0, 0x80 | (value & 0x7F))
        value >>= 7
    return bytes(out)


def build_index(entries: list[bytes], *, version: int = 2, count: int | None = None,
                extensions: list[tuple[bytes, bytes]] = (), signature: bytes = b"DIRC",
                trailer: bytes | None = None, tail: bytes = b"") -> bytes:
    body = struct.pack(">4sII", signature, version, len(entries) if count is None else count)
    body += b"".join(entries)
    for name, data in extensions:
        body += name + struct.pack(">I", len(data)) + data
    body += tail
    checksum = hashlib.sha1(body, usedforsecurity=False).digest()
    return body + (checksum if trailer is None else trailer)


def simple_entries(paths: list[bytes], version: int = 2) -> list[bytes]:
    out, previous = [], b""
    for path in paths:
        out.append(entry_bytes(path, version=version, previous=previous))
        previous = path
    return out


def tree_node(name: bytes, count: int | bytes, subtrees: int | bytes, *,
              with_oid: bool | None = None) -> bytes:
    count_text = count if isinstance(count, bytes) else str(count).encode()
    subtree_text = subtrees if isinstance(subtrees, bytes) else str(subtrees).encode()
    node = name + b"\0" + count_text + b" " + subtree_text + b"\n"
    if with_oid if with_oid is not None else (isinstance(count, int) and count >= 0):
        node += OID
    return node


def reuc_record(path: bytes, modes: tuple[bytes, bytes, bytes], oids: int | None = None
                ) -> bytes:
    record = path + b"\0" + b"".join(m + b"\0" for m in modes)
    wanted = sum(m != b"0" for m in modes) if oids is None else oids
    return record + OID * wanted
