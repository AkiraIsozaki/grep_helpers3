"""決定的ツリー走査。relpath 昇順・glob・サイズ/バイナリ skip・

生成コード既定除外・symlink は既定で辿らず realpath 重複排除。走査順非依存決定的。
"""

import fnmatch
import os
from collections.abc import Iterator
from pathlib import Path

from grep_analyzer.diagnostics import Diagnostics

# 対象言語（Java/C/Pro*C/SQL/Shell）に合わせた保守的な既定除外。
# Python/JS 生成物は対象外のため含めない。具体的な除外集合は実装委任。
DEFAULT_EXCLUDE: tuple[str, ...] = (
    "**/target/**", "**/build/**", "**/generated/**", "**/.git/**")


def _match_one(relpath: str, pat: str) -> bool:
    rel_segs = relpath.split("/")
    pat_segs = pat.split("/")

    def match_segments(rel_idx: int, pat_idx: int) -> bool:
        if pat_idx == len(pat_segs):
            return rel_idx == len(rel_segs)
        if pat_segs[pat_idx] == "**":
            return any(match_segments(k, pat_idx + 1)
                       for k in range(rel_idx, len(rel_segs) + 1))
        if rel_idx == len(rel_segs):
            return False
        return (fnmatch.fnmatch(rel_segs[rel_idx], pat_segs[pat_idx])
                and match_segments(rel_idx + 1, pat_idx + 1))

    return match_segments(0, 0)


def _match_any(relpath: str, patterns: list[str]) -> bool:
    base = relpath.rsplit("/", 1)[-1]
    for p in patterns:
        if _match_one(relpath, p) or ("/" not in p and fnmatch.fnmatch(base, p)):
            return True
    return False


def is_contained_relpath(relpath: str) -> bool:
    """relpath が source_root 配下に収まる安全な相対パスか。

    絶対パス・空・`..` を含むパスを拒否する（パストラバーサル／絶対パス注入の防御）。
    """
    if not relpath or os.path.isabs(relpath):
        return False
    return ".." not in Path(relpath).parts


def is_within_root(root, target) -> bool:
    """target の realpath が root の realpath 配下か（symlink 越えの脱出を拒否）。"""
    root_real = os.path.realpath(root)
    target_real = os.path.realpath(target)
    return target_real == root_real or target_real.startswith(root_real + os.sep)


def _is_binary(path: Path) -> bool:
    with open(path, "rb") as f:
        return b"\x00" in f.read(8192)


_PREFIX = 64 * 1024
# UTF-16/32 BOM はいずれも "unsafe" を返すため並び順は分類結果に影響しない。
# ただし UTF-32-LE(\xff\xfe\x00\x00) を UTF-16-LE(\xff\xfe) より前に置いて意図を明示する。
_BOMS = (b"\x00\x00\xfe\xff", b"\xff\xfe\x00\x00", b"\xff\xfe", b"\xfe\xff")


def _classify_bytes(head: bytes) -> str:
    """先頭バイト列を 'binary'(NUL) / 'unsafe'(UTF-16/32 BOM=非ASCII透過) / 'ok' に分類。

    NUL 走査は _PREFIX(64KiB) 全域＝_is_binary の 8KiB より厳格（_walk_classified 専用）。
    """
    for bom in _BOMS:
        if head.startswith(bom):
            return "unsafe"
    if b"\x00" in head:
        return "binary"
    return "ok"


def _collect_candidates(
    root: Path, *, include: list[str], exclude: list[str],
    follow_symlinks: bool, diag: Diagnostics | None,
) -> list[tuple[str, Path]]:
    """os.walk で候補ファイルを exclude/include/symlink フィルタ後 relpath 昇順で返す。

    サイズ/バイナリ skip・realpath 重複排除は呼び出し側の責務。walk_files と
    _walk_classified はこの収集結果に各々の判定を被せるだけで分岐する。
    """
    root = Path(root)
    candidates: list[tuple[str, Path]] = []
    visited_dirs: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        if follow_symlinks:
            # ディレクトリ symlink 循環の無限再帰を枝刈り（os.walk は検出しない）。
            real_dir = os.path.realpath(dirpath)
            if real_dir in visited_dirs:
                dirnames[:] = []
                continue
            visited_dirs.add(real_dir)
        dirnames.sort()
        for name in sorted(filenames):
            abspath = Path(dirpath) / name
            relpath = abspath.relative_to(root).as_posix()
            if abspath.is_symlink() and not follow_symlinks:
                if diag is not None:
                    diag.add("symlink_skipped", relpath)
                continue
            if _match_any(relpath, exclude):
                if diag is not None:
                    diag.add("walk_excluded", relpath)
                continue
            if include and not _match_any(relpath, include):
                continue
            candidates.append((relpath, abspath))
    return sorted(candidates)


def walk_files(
    root: Path, *, include: list[str], exclude: list[str],
    follow_symlinks: bool, max_file_bytes: int, diag: Diagnostics,
) -> Iterator[tuple[str, Path]]:
    """root 配下の通常ファイルを relpath 昇順で yield。"""
    seen_real: dict[str, str] = {}
    for relpath, abspath in _collect_candidates(
            root, include=include, exclude=exclude,
            follow_symlinks=follow_symlinks, diag=diag):
        try:
            if abspath.stat().st_size > max_file_bytes:
                diag.add("walk_skipped_large", relpath)
                continue
            if _is_binary(abspath):
                diag.add("walk_skipped_binary", relpath)
                continue
            real = os.path.realpath(abspath)
        except OSError:
            diag.add("walk_unreadable", relpath)
            continue
        if real in seen_real:
            diag.add("symlink_dedup", f"{relpath} -> {seen_real[real]}")
            continue
        seen_real[real] = relpath
        yield relpath, abspath


def collect_files(
    root: Path, *, include: list[str], exclude: list[str],
    follow_symlinks: bool, max_file_bytes: int, diag: Diagnostics,
) -> list[tuple[str, Path]]:
    """walk_files を一度だけ materialize し relpath 昇順の list を返す。

    走査・診断は1回（pipeline が keyword 横断で共有するため診断重複なし）。
    """
    return list(walk_files(
        root, include=include, exclude=exclude, follow_symlinks=follow_symlinks,
        max_file_bytes=max_file_bytes, diag=diag))


def _walk_classified(
    root: Path, *, include: list[str], exclude: list[str],
    follow_symlinks: bool, max_file_bytes: int, diag: Diagnostics | None,
) -> Iterator[tuple[str, Path, str, int]]:
    """walk_files と同構造で _classify_bytes 分類を追加し (relpath, abspath, kind, size) を yield。

    kind ∈ {"ok","unsafe"}。binary は walk_skipped_binary でスキップ。
    size は large 判定に使った単一 stat の st_size をそのまま持ち回る
    （collect_files_ex 側での再 stat を排し、二重 stat ＋ walk 後 TOCTOU の
    未捕捉 OSError を構造的に防ぐ）。
    順序・large/symlink/dedup/exclude/include 処理は walk_files と同一
    （候補収集は _collect_candidates を共有。判定は binary→kind 付与に差し替え）。
    """
    seen_real: dict[str, str] = {}
    for relpath, abspath in _collect_candidates(
            root, include=include, exclude=exclude,
            follow_symlinks=follow_symlinks, diag=diag):
        try:
            size = abspath.stat().st_size
            if size > max_file_bytes:
                if diag is not None:
                    diag.add("walk_skipped_large", relpath)
                continue
            with open(abspath, "rb") as f:
                head = f.read(_PREFIX)
            kind = _classify_bytes(head)
            if kind == "binary":
                if diag is not None:
                    diag.add("walk_skipped_binary", relpath)
                continue
            real = os.path.realpath(abspath)
        except OSError:
            if diag is not None:
                diag.add("walk_unreadable", relpath)
            continue
        if real in seen_real:
            if diag is not None:
                diag.add("symlink_dedup", f"{relpath} -> {seen_real[real]}")
            continue
        seen_real[real] = relpath
        yield relpath, abspath, kind, size


def collect_files_ex(
    root: Path, *, include: list[str], exclude: list[str],
    follow_symlinks: bool, max_file_bytes: int, diag: Diagnostics | None,
    on_progress=None, progress_every: int = 5000,
) -> tuple[list[tuple[str, Path]], int, set[str]]:
    """collect_files の拡張版。(files, total_bytes, unsafe_rels) を返す。

    total_bytes は yield されたファイルのみ累算（large/binary/dedup 除外後）。
    unsafe_rels は UTF-16/32 BOM 等の非ASCII透過ファイル（prefilter で常に走査対象に残す）。
    on_progress: 受理ファイル数が progress_every の倍数に達するたびに on_progress(count) を呼ぶ。
    """
    files, unsafe, total = [], set(), 0
    accepted = 0
    for relpath, abspath, kind, size in _walk_classified(
            root, include=include, exclude=exclude, follow_symlinks=follow_symlinks,
            max_file_bytes=max_file_bytes, diag=diag):
        files.append((relpath, abspath))
        total += size                     # walk の単一 stat 由来（再 stat しない）
        if kind == "unsafe":
            unsafe.add(relpath)
        accepted += 1
        if on_progress is not None and accepted % progress_every == 0:
            on_progress(accepted)
    return files, total, unsafe
