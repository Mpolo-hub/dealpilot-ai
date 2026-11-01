"""Strict, read-only reader for Git's `.git/index` (spec 003 O2, section 13.3).

Standard library only: the file is read in one call and parsed in memory. Nothing is ever
written, refreshed or locked. Anything unknown, unsupported, malformed or ambiguous raises
`IndexRejected`; the clean-tree controller turns that into a refusal (fail closed).

Format: `Documentation/gitformat-index` of Git 2.56. Supported: versions 2, 3 and 4 with
SHA-1 object names and a verified trailing checksum. Extensions: only those in
`ACCEPTED_EXTENSIONS`, each validated structurally (TREE, REUC); every other extension,
optional or required, is refused.
"""
from __future__ import annotations

import hashlib
import os
import re
import struct
import unicodedata
from dataclasses import dataclass
from pathlib import Path

MAX_INDEX_BYTES = 64 * 1024 * 1024
SUPPORTED_VERSIONS = (2, 3, 4)
OID_SIZE = 20  # SHA-1 only
TRAILER_SIZE = 20
ENTRY_FIXED_SIZE = 62  # 10 x 32-bit stat fields, object name, 16-bit flags
MAX_TREE_DEPTH = 4096
MAX_COUNT = 2**31 - 1

# Entry flags (gitformat-index, "Index entry").
ASSUME_VALID = 0x8000
EXTENDED = 0x4000
STAGE_MASK = 0x3000
NAME_MASK = 0x0FFF
# Extended flags (versions 3 and 4): reserved, skip-worktree, intent-to-add, 13 unused.
EXT_RESERVED = 0x8000
EXT_SKIP_WORKTREE = 0x4000
EXT_INTENT_TO_ADD = 0x2000

MODE_REGULAR = 0o100644
MODE_EXECUTABLE = 0o100755
MODE_SYMLINK = 0o120000
MODE_GITLINK = 0o160000
ENTRY_MODES = (MODE_REGULAR, MODE_EXECUTABLE, MODE_SYMLINK)
REUC_MODES = (0, MODE_REGULAR, MODE_EXECUTABLE, MODE_SYMLINK, MODE_GITLINK)

ACCEPTED_EXTENSIONS = frozenset({b"TREE", b"REUC"})

_TREE_COUNT = re.compile(rb"-1|0|[1-9][0-9]*")
_TREE_SUBTREES = re.compile(rb"0|[1-9][0-9]*")
_OCTAL_MODE = re.compile(rb"0|[1-7][0-7]*")


class IndexRejected(Exception):
    """The index can't be trusted. `code` is stable; `detail` is a safe representation."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class IndexEntry:
    path: str
    mode: int
    stage: int
    oid: bytes


@dataclass(frozen=True)
class IndexSnapshot:
    version: int
    entries: tuple[IndexEntry, ...]
    extensions: tuple[str, ...]
    conflict_paths: tuple[str, ...]
    sha256: str
    stat: tuple[int, int, int]  # size, mtime_ns, inode
    tree: tuple[tuple[str, int, int, str | None], ...] = ()
    resolve_undo: tuple[tuple[str, tuple[tuple[int, str | None], ...]], ...] = ()


# --------------------------------------------------------------------------- paths

def safe_text(value: str | bytes) -> str:
    """A diagnostic form that never holds control or non-ASCII characters."""
    if isinstance(value, bytes):
        return "hex:" + value[:64].hex()
    return ascii(value)[:200]


def check_path_text(text: str, *, component: bool = False) -> str:
    """Spec 003 section 13.3 path policy: UTF-8, NFC, no unsafe parts. Never normalizes."""
    try:
        text.encode("utf-8", "strict")  # lone surrogates from tolerant decoding fail here
    except UnicodeEncodeError:
        raise IndexRejected("path_not_utf8", safe_text(text)) from None
    if unicodedata.normalize("NFC", text) != text:
        raise IndexRejected("path_not_nfc", safe_text(text))
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in text) or "\\" in text:
        raise IndexRejected("path_bad_character", safe_text(text))
    parts = [text] if component else text.split("/")
    if not text or (component and "/" in text):
        raise IndexRejected("path_bad_form", safe_text(text))
    for part in parts:
        if part in ("", ".", "..") or part.casefold() == ".git":
            raise IndexRejected("path_bad_form", safe_text(text))
    return text


def check_path_bytes(raw: bytes, *, component: bool = False) -> str:
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError:
        raise IndexRejected("path_not_utf8", safe_text(raw)) from None
    return check_path_text(text, component=component)


# --------------------------------------------------------------------------- reading

def file_stat(path: Path) -> tuple[int, int, int]:
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns, st.st_ino


def read_index(path: Path, accepted_extensions: frozenset[bytes] = ACCEPTED_EXTENSIONS
               ) -> IndexSnapshot:
    """One read-only snapshot: stat, a single read, stat again, then a strict parse."""
    try:
        before = file_stat(path)
        if before[0] > MAX_INDEX_BYTES:
            raise IndexRejected("index_too_large", str(before[0]))
        with open(path, "rb") as handle:
            data = handle.read(MAX_INDEX_BYTES + 1)
        after = file_stat(path)
    except FileNotFoundError:
        raise IndexRejected("index_missing") from None
    except OSError as error:
        raise IndexRejected("index_unreadable", type(error).__name__) from None
    if before != after or len(data) != after[0]:
        raise IndexRejected("index_changed_during_read")
    return parse_index(data, accepted_extensions, stat=after)


def parse_index(data: bytes, accepted_extensions: frozenset[bytes] = ACCEPTED_EXTENSIONS,
                *, stat: tuple[int, int, int] = (0, 0, 0)) -> IndexSnapshot:
    """Parse index bytes fully, in memory. Raises `IndexRejected` on anything doubtful."""
    if len(data) < 12 + TRAILER_SIZE:
        raise IndexRejected("index_truncated")
    trailer = data[-TRAILER_SIZE:]
    if trailer == bytes(TRAILER_SIZE):
        raise IndexRejected("index_checksum_skipped")  # index.skipHash
    # Git's own index checksum is SHA-1; it detects corruption, it is not a security check.
    if hashlib.sha1(data[:-TRAILER_SIZE], usedforsecurity=False).digest() != trailer:
        raise IndexRejected("index_checksum_mismatch")
    signature, version, count = struct.unpack_from(">4sII", data, 0)
    if signature != b"DIRC":
        raise IndexRejected("index_bad_signature")
    if version not in SUPPORTED_VERSIONS:
        raise IndexRejected("index_unsupported_version", str(version))
    body = data[:-TRAILER_SIZE]
    end = len(body)
    pos = 12
    entries: list[IndexEntry] = []
    previous_name = b""
    previous_key: tuple[bytes, int] | None = None
    stages_by_name: dict[bytes, list[int]] = {}
    for _ in range(count):
        entry, name, pos = _read_entry(body, pos, end, version, previous_name)
        key = (name, entry.stage)
        if previous_key is not None and key <= previous_key:
            raise IndexRejected("index_entries_unsorted", safe_text(name))
        previous_key, previous_name = key, name
        stages_by_name.setdefault(name, []).append(entry.stage)
        entries.append(entry)
    conflicts = []
    for name, stages in stages_by_name.items():
        if stages != [0]:
            if 0 in stages:  # a path is either merged (stage 0) or conflicted (1 to 3)
                raise IndexRejected("index_stage_mix", safe_text(name))
            conflicts.append(check_path_bytes(name))
    extensions, tree, resolve_undo = _read_extensions(body, pos, end, count,
                                                      accepted_extensions)
    return IndexSnapshot(version, tuple(entries), extensions, tuple(conflicts),
                         hashlib.sha256(data).hexdigest(), stat, tuple(tree),
                         tuple(sorted(resolve_undo.items())))


def _need(end: int, pos: int, size: int, what: str) -> None:
    if size < 0 or pos + size > end:
        raise IndexRejected("index_truncated", what)


def _read_entry(body: bytes, pos: int, end: int, version: int, previous_name: bytes
                ) -> tuple[IndexEntry, bytes, int]:
    start = pos
    _need(end, pos, ENTRY_FIXED_SIZE, "entry")
    fields = struct.unpack_from(">10I", body, pos)
    mode = fields[6]
    oid = body[pos + 40:pos + 40 + OID_SIZE]
    (flags,) = struct.unpack_from(">H", body, pos + 60)
    pos += ENTRY_FIXED_SIZE
    if flags & ASSUME_VALID:
        raise IndexRejected("index_assume_unchanged")
    if flags & EXTENDED:
        if version == 2:
            raise IndexRejected("index_extended_flag_in_v2")
        _need(end, pos, 2, "extended flags")
        (extended,) = struct.unpack_from(">H", body, pos)
        pos += 2
        if extended & EXT_SKIP_WORKTREE:
            raise IndexRejected("index_skip_worktree")
        if extended & EXT_INTENT_TO_ADD:
            raise IndexRejected("index_intent_to_add")
        if extended & EXT_RESERVED or extended & ~(EXT_SKIP_WORKTREE | EXT_INTENT_TO_ADD):
            raise IndexRejected("index_unknown_extended_flag", hex(extended))
        raise IndexRejected("index_empty_extended_flags")  # Git never writes this
    stage = (flags & STAGE_MASK) >> 12
    name_length = flags & NAME_MASK
    if version == 4:
        strip, pos = _read_varint(body, pos, end)
        if strip > len(previous_name):
            raise IndexRejected("index_bad_prefix")
        nul = _find_nul(body, pos, end)
        name = previous_name[:len(previous_name) - strip] + body[pos:nul]
        pos = nul + 1
    else:
        nul = _find_nul(body, pos, end)
        name = body[pos:nul]
        size = ((pos - start) + len(name) + 8) & ~7  # 1 to 8 NUL bytes of padding
        _need(end, start, size, "entry padding")
        if any(body[nul:start + size]):
            raise IndexRejected("index_bad_padding")
        pos = start + size
    if (name_length < NAME_MASK and len(name) != name_length) or (
            name_length == NAME_MASK and len(name) < NAME_MASK):
        raise IndexRejected("index_bad_name_length")
    path = check_path_bytes(name)
    if mode == MODE_GITLINK:
        raise IndexRejected("index_gitlink_entry", safe_text(path))
    if mode not in ENTRY_MODES:
        raise IndexRejected("index_bad_mode", oct(mode))
    return IndexEntry(path, mode, stage, oid), name, pos


def _find_nul(body: bytes, pos: int, end: int) -> int:
    index = body.find(b"\0", pos, end)
    if index < 0:
        raise IndexRejected("index_truncated", "name")
    return index


def _read_varint(body: bytes, pos: int, end: int) -> tuple[int, int]:
    """Git's offset varint (the OFS_DELTA encoding), bounded."""
    _need(end, pos, 1, "varint")
    byte = body[pos]
    pos += 1
    value = byte & 0x7F
    while byte & 0x80:
        value += 1
        if value > MAX_COUNT:
            raise IndexRejected("index_bad_prefix")
        _need(end, pos, 1, "varint")
        byte = body[pos]
        pos += 1
        value = (value << 7) + (byte & 0x7F)
    if value > MAX_COUNT:
        raise IndexRejected("index_bad_prefix")
    return value, pos


# --------------------------------------------------------------------------- extensions

def _read_extensions(body: bytes, pos: int, end: int, count: int,
                     accepted: frozenset[bytes]) -> tuple[tuple[str, ...], list, dict]:
    seen: list[str] = []
    tree: list = []
    resolve_undo: dict = {}
    while pos < end:
        _need(end, pos, 8, "extension header")
        signature = body[pos:pos + 4]
        (size,) = struct.unpack_from(">I", body, pos + 4)
        pos += 8
        _need(end, pos, size, "extension data")
        data = body[pos:pos + size]
        pos += size
        name = signature.decode("ascii", "replace")
        if signature not in accepted or not signature.isalpha():
            raise IndexRejected("index_unsupported_extension", safe_text(signature))
        if name in seen:
            raise IndexRejected("index_duplicate_extension", name)
        if signature == b"TREE":
            tree = parse_tree_extension(data, count)
        elif signature == b"REUC":
            resolve_undo = parse_reuc_extension(data)
        seen.append(name)
    if pos != end:
        raise IndexRejected("index_trailing_bytes")
    return tuple(seen), tree, resolve_undo


def _read_until(data: bytes, pos: int, delimiter: bytes, what: str) -> tuple[bytes, int]:
    index = data.find(delimiter, pos)
    if index < 0:
        raise IndexRejected("extension_truncated", what)
    return data[pos:index], index + 1


def _subtree_key(name: bytes) -> tuple[int, bytes]:
    """Git's `subtree_name_cmp`: shorter names first, then bytes (cache-tree.c)."""
    return len(name), name


def parse_tree_extension(data: bytes, entry_count: int
                         ) -> list[tuple[str, int, int, str | None]]:
    """Validate TREE (cache-tree) strictly; its content is never used to judge cleanliness.

    Returns the nodes in file order as (directory path, entry count, subtrees, object name
    in hex or None for an invalid node); the root's path is "".
    """
    pos = 0
    stack: list[list] = []  # [subtrees still expected, previous sibling name, path]
    nodes: list[tuple[str, int, int, str | None]] = []
    root = True
    while root or stack:
        if stack and stack[-1][0] == 0:
            stack.pop()
            continue
        name, pos = _read_until(data, pos, b"\0", "tree name")
        if root:
            if name:
                raise IndexRejected("tree_root_not_first")
            path = ""
        else:
            component = check_path_bytes(name, component=True)
            parent = stack[-1]
            if parent[1] is not None and _subtree_key(name) <= _subtree_key(parent[1]):
                raise IndexRejected("tree_subtrees_unsorted", safe_text(name))
            parent[0] -= 1
            parent[1] = name
            path = f"{parent[2]}/{component}" if parent[2] else component
        count_text, pos = _read_until(data, pos, b" ", "tree count")
        subtree_text, pos = _read_until(data, pos, b"\n", "tree subtrees")
        if not _TREE_COUNT.fullmatch(count_text) or not _TREE_SUBTREES.fullmatch(subtree_text):
            raise IndexRejected("tree_bad_number")
        count, subtrees = int(count_text), int(subtree_text)
        if count > entry_count or count > MAX_COUNT or subtrees > MAX_COUNT:
            raise IndexRejected("tree_bad_number")
        oid = None
        if count >= 0:
            if pos + OID_SIZE > len(data):
                raise IndexRejected("extension_truncated", "tree object name")
            oid = data[pos:pos + OID_SIZE].hex()
            pos += OID_SIZE
        if len(stack) >= MAX_TREE_DEPTH:
            raise IndexRejected("tree_too_deep")
        nodes.append((path, count, subtrees, oid))
        stack.append([subtrees, None, path])
        root = False
    if pos != len(data):
        raise IndexRejected("tree_trailing_bytes")
    return nodes


def parse_reuc_extension(data: bytes) -> dict[str, tuple[tuple[int, str | None], ...]]:
    """Validate REUC (resolve undo) strictly; its content is never used to judge cleanliness.

    Returns {path: ((mode, object name hex or None) for stages 1, 2 and 3)}.
    """
    pos = 0
    previous: bytes | None = None
    records: dict[str, tuple[tuple[int, str | None], ...]] = {}
    while pos < len(data):
        name, pos = _read_until(data, pos, b"\0", "reuc path")
        path = check_path_bytes(name)
        if previous is not None and name <= previous:
            raise IndexRejected("reuc_unsorted", safe_text(name))
        previous = name
        modes = []
        for _ in range(3):
            text, pos = _read_until(data, pos, b"\0", "reuc mode")
            if not _OCTAL_MODE.fullmatch(text) or int(text, 8) not in REUC_MODES:
                raise IndexRejected("reuc_bad_mode", safe_text(text))
            modes.append(int(text, 8))
        if not any(modes):
            raise IndexRejected("reuc_no_stage")
        stages = []
        for mode in modes:
            oid = None
            if mode:
                if pos + OID_SIZE > len(data):
                    raise IndexRejected("extension_truncated", "reuc object name")
                oid = data[pos:pos + OID_SIZE].hex()
                pos += OID_SIZE
            stages.append((mode, oid))
        records[path] = tuple(stages)
    return records
