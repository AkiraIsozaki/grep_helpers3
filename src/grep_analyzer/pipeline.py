"""direct と不動点 indirect を併合するパイプラインである。"""

import os
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from grep_analyzer import output_writer, resume, ripgrep
from grep_analyzer.classify import classify_hit
from grep_analyzer.diagnostics import Diagnostics, SECTION_8_4_CATEGORIES
from grep_analyzer.dispatch import (
    LANG_SAMPLE_BYTES,
    extension_resolves_language,
    shebang_dialect,
    shebang_language,
)
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint_multi
from grep_analyzer.fixedpoint._encmemo import EncMemo
from grep_analyzer.fixedpoint._seed import initialize_state
from grep_analyzer.ingest import parse_grep_line
from grep_analyzer.model import Hit
from grep_analyzer.snippet import build_snippet
from grep_analyzer.snippet._sanitize_line import _physical_lines
from grep_analyzer.tsv import sanitize_field
from grep_analyzer.walk import (
    DEFAULT_EXCLUDE,
    collect_files_ex,
    is_contained_relpath,
    is_within_root,
)


def _default_opts() -> EngineOptions:
    # 既定値は EngineOptions（_options.py）が単一情報源。exclude のみ本番既定を明示。
    return EngineOptions(exclude=list(DEFAULT_EXCLUDE))


def _effective_use_ripgrep(explicit: bool | None, total_bytes: int, threshold: int) -> bool:
    """tri-state を実効 bool に解決。明示(True/False)優先、None は rg 可用かつ総バイト>=閾値。"""
    if explicit is not None:
        return explicit
    return ripgrep.available() and total_bytes >= threshold


def _direct_hits_for_keyword(keyword, lines, grep_name, grep_enc, source_root,
                             opts, enc_memo, decode_cache, fb, lang_map, kw_diag):
    """1 keyword の grep 行から direct Hit のリストを構築する。

    grep 出力はファイル単位でヒットがまとまる（grep -rn / rg）。直前 1 ファイル分の
    読込・復号・言語判定・パース木を cur_ctx にキャッシュし、同一ファイルの連続ヒットで
    ディスク再読込と tree-sitter 再パースを抑止する（追加メモリ O(1)＝1 ファイル分）。
    `cur_ctx is None ⇔ 現 relpath は非ファイル` を構造的不変条件にする（別フラグとの
    手動同期を排し、欠落診断の取りこぼしを防ぐ）。診断（decode_replaced/
    unsupported_shebang/missing_source）は件数・順序を保つためヒット行ごとに発火する。
    """
    from grep_analyzer.fixedpoint._scan import meta_via_decode_cache, read_bytes_with_sig
    hits: list[Hit] = []
    cur_relpath = None
    cur_ctx: tuple | None = None
    for raw_line in lines:
        parsed = parse_grep_line(raw_line)
        if parsed is None:
            kw_diag.add("bad_grep_line", f"{grep_name}: {raw_line!r}")
            continue
        path_bytes, lineno, content_bytes = parsed
        # パスは生バイト由来＝os.fsdecode（FS codec＋surrogateescape）で FS と一致。
        # walk.py の relpath 表現とも統一され、SJIS 混在名でも is_file が当たる。
        relpath = os.fsdecode(path_bytes)
        content = content_bytes.decode(grep_enc, errors="replace")
        if relpath != cur_relpath:
            cur_relpath = relpath
            target = Path(source_root) / relpath
            if is_contained_relpath(relpath) and target.is_file() and is_within_root(source_root, target):
                # direct も seed/scan/finalize と同じ永続デコードキャッシュ経路
                # （meta_via_decode_cache）を通す。decode/言語判定を hop・worker・run をまたいで
                # ファイルにつき 1 回に固定する（#1: 旧 direct は cache 非経由で
                # 同一 run 内に seed と二重 decode していた）。language/dialect は
                # _meta_from_text が LANG_SAMPLE_BYTES 窓で確定し scan/indirect と同値。
                try:
                    # bytes と read 時 sig を同一 fd で取得（put の stale 化を防ぐ・L1）。
                    raw, sig = read_bytes_with_sig(target)
                except OSError:
                    # is_file 後の TOCTOU（消失/権限変化）。seed/scan と同じく run を
                    # 落とさず欠落扱い（missing_source）へ降格する（L3）。
                    cur_ctx = None
                else:
                    file_text, enc, replaced, language, dialect = meta_via_decode_cache(
                        enc_memo, decode_cache, str(target), relpath,
                        raw, lang_map, fb, fast=opts.fast_encoding, sig=sig)
                    sample = file_text[:LANG_SAMPLE_BYTES]
                    unsupported = (
                        not extension_resolves_language(relpath, lang_map)
                        and shebang_dialect(sample) is not None  # シェバン行が存在
                        and shebang_language(sample) is None      # 対応言語に解決しない
                    )
                    cur_ctx = (file_text, enc, replaced, language, dialect,
                               unsupported, {}, _physical_lines(file_text))
            else:
                cur_ctx = None
        if cur_ctx is None:
            # パスは sanitize_field を通す。Unix パスは TAB/CR を含み得るが、
            # diagnostics の detail 行は `{category}\t{message}` 形式なので生 TAB/CR が
            # 列・行構造を壊す（TSV の file 列と同じ規約に揃える・M2）。
            kw_diag.add("missing_source", sanitize_field(relpath))
            continue
        (file_text, enc, replaced, language, dialect,
         unsupported, tree_cache, phys_lines) = cur_ctx
        if replaced:
            kw_diag.add("decode_replaced", sanitize_field(str(relpath)))
        if unsupported:
            kw_diag.add("unsupported_shebang", sanitize_field(str(relpath)))
        category, confidence = classify_hit(
            language, dialect, file_text, lineno, content, cache=tree_cache)
        hits.append(Hit(
            keyword=keyword, language=language, file=relpath, lineno=lineno,
            ref_kind="direct", category=category, category_sub="",
            usage_summary=f"{category} ({language})", via_symbol="",
            chain=f"{keyword}@{relpath}:{lineno}",
            snippet=build_snippet(language, dialect, file_text, lineno,
                                  cache=tree_cache, lines=phys_lines),
            encoding=enc + (" 要確認" if replaced else ""), confidence=confidence,
        ))
    return hits


def run(
    input_dir: Path, output_dir: Path, source_root: Path,
    opts: EngineOptions | None = None,
) -> int:
    """input/*.grep を処理し、direct＋不動点 indirect を併合した TSV を出力する。

    全 keyword を1本の lock-step 走査（run_fixedpoint_multi）で処理する転置構造である。
    direct 構築は keyword 単位に byte 同値で、enc_memo は run 全体で共有する。
    diagnostics は逐次版の追記順（walk → keyword ソート順に [direct, indirect]）を
    merge_in_order で再現する。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    # root realpath キャッシュは run をまたいで持ち越さない（同一プロセスで source_root が
    # 別実体へ張り替わったときの stale 判定を防ぐ・F2）。
    from grep_analyzer.walk import _realpath_root
    _realpath_root.cache_clear()
    if opts is None:
        opts = _default_opts()
    _auto_cache_dir = None
    if opts.decode_cache_dir is None:
        _auto_cache_dir = Path(tempfile.mkdtemp(prefix="ga_decode_"))
        opts = replace(opts, decode_cache_dir=_auto_cache_dir)
    try:
        lang_map = opts.lang_map
        # --- 1. walk + 実効 use_ripgrep 解決（walk 由来診断は walk_diag に集約） ---
        walk_diag = Diagnostics()
        # collect_files_ex: 64KiB NUL prefix（_is_binary と同一窓・#I 統一）＋ total_bytes/unsafe_rels を prefilter 判定に利用する
        def _walk_cb(count):
            print(f"[grep_analyzer] walking {count} files...", file=sys.stderr, flush=True)
        files, total_bytes, unsafe_rels = collect_files_ex(
            Path(source_root), include=opts.include, exclude=opts.exclude,
            follow_symlinks=opts.follow_symlinks,
            max_file_bytes=opts.max_file_bytes, diag=walk_diag,
            on_progress=_walk_cb if opts.progress == "on" else None)
        use_rg_override = opts.use_ripgrep
        use_rg = _effective_use_ripgrep(
            use_rg_override, total_bytes, opts.ripgrep_threshold_bytes)
        opts = replace(opts, use_ripgrep=use_rg)
        if use_rg_override is None and use_rg:
            walk_diag.add("prefilter_auto_engaged",
                          f"total_bytes={total_bytes} threshold={opts.ripgrep_threshold_bytes}")

        fb = list(opts.encoding_fallback) or DEFAULT_FALLBACK
        # run 共有 enc-memo：direct/seed/finalize の再読込で keyword をまたいで chardet を重複排除する
        # （jobs>1 の並列 SCAN は process-local の _WORKER_ENC を使い fork 越しに共有不可）。
        # キーは str(abspath)（未正規化）だが memo は純粋なのでキー差異は性能劣化に留まり出力不変。
        enc_memo = EncMemo()
        from grep_analyzer.fixedpoint._scan import make_decode_cache
        # namespace は decode_cache_namespace(opts) が fast/fallback/lang_map を畳み込む（C1）。
        decode_cache = make_decode_cache(opts)

        # --- 2. keyword 単位 direct 構築（既存ロジックを verbatim 流用） ---
        direct_hits: dict[str, list[Hit]] = {}
        direct_diag: dict[str, Diagnostics] = {}
        resume_skipped: list[str] = []
        kw_fingerprint: dict[str, str] = {}
        for grep_file in sorted(Path(input_dir).glob("*.grep")):
            keyword = grep_file.stem
            grep_bytes = grep_file.read_bytes()
            # 入力指紋（.grep 本文＋行に影響する opts＋source_root）。resume の完了判定に渡し、
            # finalize で manifest に焼き込む。入力/オプションが変われば再処理させる（H1）。
            fp = resume.compute_inputs_fingerprint(grep_bytes, source_root, opts)
            # resume: 完了済 keyword は direct も states も finalize も行わずスキップ。
            if opts.resume and resume.is_complete(output_dir, keyword, opts, fp):
                resume_skipped.append(keyword)
                continue
            kw_fingerprint[keyword] = fp
            kw_diag = Diagnostics()
            direct_diag[keyword] = kw_diag
            # content 復号用にファイル単位で文字コードを 1 回だけ判定（chardet 1回・行間一貫）。
            # パスは生バイトのまま os.fsdecode するため、ここでは encoding のみ使う。
            _, grep_enc, _ = decode_bytes(grep_bytes, fb, fast=opts.fast_encoding)
            lines = grep_bytes.split(b"\n")
            if lines and lines[-1] == b"":
                lines.pop()                       # 末尾改行による空要素（splitlines 相当）
            direct_hits[keyword] = _direct_hits_for_keyword(
                keyword, lines, grep_file.name, grep_enc, source_root, opts,
                enc_memo, decode_cache, fb, lang_map, kw_diag)

        # --- 3. states 構築（同一 keyword ソート順・keyword 別 indirect_diag） ---
        indirect_diag: dict[str, Diagnostics] = {}
        states_by_kw = {}
        for kw in direct_hits:                    # dict は挿入順＝glob ソート順を保持
            indirect_diag[kw] = Diagnostics()
            states_by_kw[kw] = initialize_state(
                direct_hits[kw], Path(source_root), opts, indirect_diag[kw],
                enc_memo=enc_memo, decode_cache=decode_cache)

        # --- 4. 1本の lock-step pass ---
        indirect = run_fixedpoint_multi(
            states_by_kw, Path(source_root), opts,
            files=files, unsafe_rels=unsafe_rels, enc_memo=enc_memo,
            decode_cache=decode_cache)

        # --- 5. finalize（keyword ソート順＝従来 glob 順と同一） ---
        src_abs = str(Path(source_root).resolve())
        for kw in sorted(states_by_kw):
            rows = [replace(h, file=f"{src_abs}/{h.file}")
                    for h in direct_hits[kw] + indirect[kw]]
            output_writer.finalize(output_dir, kw, rows, opts,
                                   inputs_fingerprint=kw_fingerprint[kw])

        # --- 6. diagnostics 併合（逐次版の diag 追記順を再現） ---
        # 逐次版順序: walk → keyword ソート順に [direct diags, indirect diags]。
        # merge_in_order はカテゴリ別 detail を与えた順に連結し counts を合算する。
        # 既知制限: keyword 横断の DETAIL 順 byte 一致（automaton_split 等の共有 hop 診断）
        # は未実現。現ゲートは golden（TSV + diagnostics SUMMARY 件数）と per-keyword TSV byte 一致。
        # resume_skipped の DETAIL 順も変化している（旧: 他診断とインターリーブ／新: 末尾に
        # sorted 順でまとめて append）が件数は不変。
        diag = Diagnostics()
        ordered_diags = [walk_diag]
        for kw in sorted(states_by_kw):
            ordered_diags.append(direct_diag[kw])
            ordered_diags.append(indirect_diag[kw])
        diag.merge_in_order(ordered_diags)
        for kw in sorted(resume_skipped):
            diag.add("resume_skipped", kw)

        # SJIS 混在環境では FS 走査由来のファイル名に孤立サロゲート (U+DC80〜U+DCFF) が混じる。
        # strict UTF-8 だと "surrogates not allowed" で倒れるため backslashreplace で可視化
        # （純UTF-8維持・原因ファイルは復元可能）。
        (output_dir / "diagnostics.txt").write_text(
            diag.render(detail_limit=opts.diagnostics_detail_limit,
                        exempt=SECTION_8_4_CATEGORIES),
            encoding="utf-8", errors="backslashreplace")
        n_large = walk_diag.counts().get("walk_skipped_large", 0)
        if n_large:
            print(f"[grep_analyzer] 警告: {n_large} 件のファイルが "
                  f"--max-file-bytes({opts.max_file_bytes}) 超で除外されました "
                  f"（詳細は diagnostics.txt の walk_skipped_large）", file=sys.stderr)
        # decode キャッシュの put 失敗（disk full 等）を可視化する（L-1）。
        # 失敗しても出力は正しい（再 decode に降格するだけ）が、キャッシュが効かず
        # 遅くなるため気づけるようにする。main process 分のみ（worker 分は別プロセス）。
        if decode_cache.put_failures:
            print(f"[grep_analyzer] 警告: decode キャッシュ書込が "
                  f"{decode_cache.put_failures} 件失敗しました（disk full 等? "
                  f"--decode-cache-dir の空き容量を確認してください）", file=sys.stderr)
        return 0
    finally:
        if _auto_cache_dir is not None:
            shutil.rmtree(_auto_cache_dir, ignore_errors=True)
