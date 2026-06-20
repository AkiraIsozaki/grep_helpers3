"""lock-step 共有エンジン: 全 keyword を1本の union 走査で前進させる。

グローバル hop ごとに全 keyword の active シンボルを union して1回だけ走査し、
結果を keyword 別に absorb する。単一 keyword では逐次版と byte 同値。

単一 keyword 同値の根拠:
- ghop は単一 keyword では逐次版の hop と同期。
- automaton_split / graph_spilled の `hop={ghop}` も逐次版と同一文字列。
- absorb_results には FULL pass_results を渡す（逐次版と同一入力）。
  per-relpath 副作用（encoding_of / decode_replaced）が走査済み・非ヒット relpath でも保たれる。
- compute_nchunks_union の n_live は |union 記号数| で、旧逐次版の n_live=|done 集合| とは
  意味が異なる。差が出るのは finite --memory-limit かつ hop≥2 のときのみで、
  automaton_split 診断と chunk 数にしか影響しない（どちらも出力中立）。
- progress.start/hop/done の呼出回数も単一 keyword で逐次版と一致。
"""

import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from grep_analyzer import ripgrep as _rg
from grep_analyzer.fixedpoint._budget_control import (
    apply_global_cap,
    compute_nchunks_union,
    degrade_insufficient,
    maybe_spill,
)
from grep_analyzer.fixedpoint._finalize import build_indirect_hits
from grep_analyzer.fixedpoint._ingest import absorb_results
from grep_analyzer.fixedpoint._scan import (
    decode_cache_namespace,
    make_decode_cache,
    make_file_cache,
    make_pool,
    scan_hop,
)
from grep_analyzer.progress import Progress


def run_fixedpoint_multi(states_by_kw, source_root, opts, *, files,
                         unsafe_rels=None, enc_memo=None, decode_cache=None):
    """全 keyword を lock-step で前進させ keyword 別 indirect Hit を返す。"""
    source_root = Path(source_root)
    unsafe_rels = unsafe_rels or set()
    rel_to_abs = {r: a for r, a in files}
    # main の make_decode_cache と worker の namespace は同一でなければ L2 を共有できない。
    # decode_cache_namespace は fast/encoding_fallback を畳み込む（C1）。
    # lang_map は language/dialect 判定にしか効かず復号結果を左右しないため畳み込まない。
    ns = decode_cache_namespace(opts)
    # decode_cache_dir 未指定なら temp dir を「ここで 1 度だけ」解決し opts に焼き込む（#9）。
    # これをしないと main の make_decode_cache と各 worker の _worker_init が
    # それぞれ別 mkdtemp を切り、L2 が共有されず temp dir も漏れる
    # （pipeline 本流は事前解決済みだが run_fixedpoint shim / 直接呼びがこの穴を踏む）。
    _auto_cache_dir = None
    if decode_cache is None and opts.decode_cache_dir is None:
        _auto_cache_dir = Path(tempfile.mkdtemp(prefix="ga_decode_"))
        opts = replace(opts, decode_cache_dir=_auto_cache_dir)
    if decode_cache is None:
        decode_cache = make_decode_cache(opts, namespace=ns)
    for st in states_by_kw.values():
        st.rel_to_abs = rel_to_abs
        st.enc_memo = enc_memo          # finalize が st.enc_memo を使う
        st.decode_cache = decode_cache
    progress = Progress(opts.progress)
    progress.start(len(files))
    from grep_analyzer.spill import cleanup_stale_edge_files
    cleanup_stale_edge_files(opts.spill_dir)
    file_cache = make_file_cache()
    pool = make_pool(opts, namespace=ns)
    interrupted = True
    try:
        ghop = 1
        while any(st.chase_active or st.terminal_active for st in states_by_kw.values()):
            per_kw = {}
            union = set()
            for kw, st in states_by_kw.items():
                apply_global_cap(st)
                maybe_spill(st, ghop)
                sc = {s for s in st.chase_active if s not in st.capped}
                stm = {s for s in st.terminal_active if s not in st.capped}
                st.chase_done |= st.chase_active
                st.chase_active = set()
                st.terminal_done |= st.terminal_active
                st.terminal_active = set()
                per_kw[kw] = (sc, stm)
                union |= sc | stm
            scan_symbols = sorted(union)
            if not scan_symbols or ghop > opts.max_depth:
                break
            scan_files = files
            union_keep = None       # prefilter の結果（None＝全件走査）
            if opts.use_ripgrep:
                union_keep = _rg.prefilter(source_root, rel_to_abs, scan_symbols)
                if union_keep is not None:
                    safe = union_keep | unsafe_rels
                    scan_files = [(r, a) for r, a in files if r in safe]
            # 全 state は同じ opts 由来の budget を持つので先頭を取るだけで安全である。
            nchunks = compute_nchunks_union(
                list(states_by_kw.values()), scan_symbols,
                opts=opts, budget=next(iter(states_by_kw.values())).budget)
            pass_results, n_actual_chunks = scan_hop(
                scan_symbols, scan_files, opts, nchunks,
                file_cache=file_cache, pool=pool, enc_memo=enc_memo,
                progress=progress, hop_no=ghop, decode_cache=decode_cache)
            # automaton_split は共有走査ゆえ global hop ごとに1回だけ付与する（出力中立）。
            # その hop に live 記号（sc|stm）を持つ keyword のみに付与する
            # （逐次版で走査しない kw は automaton_split を記録しないため）。
            if nchunks > 1:
                for kw, st in states_by_kw.items():
                    sc_k, stm_k = per_kw[kw]
                    if sc_k or stm_k:
                        st.diagnostics.add(
                            "automaton_split", f"hop={ghop} chunks={n_actual_chunks}")
            # 縮退不足（max_passes 頭打ちでも予算超過が残る）を live keyword に可視化する（#F）。
            if degrade_insufficient(scan_symbols, nchunks, opts=opts,
                                    budget=next(iter(states_by_kw.values())).budget,
                                    states=list(states_by_kw.values())):
                for kw, st in states_by_kw.items():
                    sc_k, stm_k = per_kw[kw]
                    if sc_k or stm_k:
                        st.diagnostics.add(
                            "degrade_chunk_capped",
                            f"hop={ghop} chunks={n_actual_chunks} union={len(scan_symbols)}")
            # per-keyword で decode_replaced/encoding_of を帰属させる。
            # 共有 union 走査は global hop ごとに1回だが、absorb の per-relpath 副作用
            # （encoding_of.setdefault / decode_replaced）は「逐次版 keyword K がその hop で
            # 走査したであろう relpath」にのみ帰属させる必要がある。
            # そうしないと他 keyword の scan 集合でしか hit しない relpath の decode_replaced が
            # 全 keyword に流入してしまう（cross-keyword pollution）。
            #
            # - prefilter OFF（keep=None／非 ASCII 記号で全件走査）: FULL pass_results をそのまま渡す。
            #   単一 keyword では union_keep も全件なので逐次版と byte 同値。
            # - prefilter ON（union_keep が絞り込み集合）: keyword K 自身の
            #   keep_K = prefilter(sorted(sc|stm), restrict_to=union_keep) | unsafe_rels で
            #   絞った pass_results を渡す。共有復号/automaton は1回のまま。per-keyword
            #   prefilter は rg subprocess を K 本追加 spawn するが、探索対象を全コーパスでなく
            #   union_keep に限定するため各走査は union_keep 分のみ（巨大コーパスで効く）。
            #   keep_K ⊆ union_keep（記号集合の部分集合性ゆえ部分文字列マッチも上位集合）が
            #   保証するので、探索空間を union_keep に絞っても結果集合は全コーパス走査と同一。
            for kw, st in states_by_kw.items():
                sc, stm = per_kw[kw]
                kw_results = pass_results
                # per-keyword 絞り込みは global prefilter が効いた（union_keep が集合の）ときだけ行う。
                # union_keep が縮小集合なら keep_k ⊆ union_keep で各 rg は安価。
                #
                # 既知の受容済み制限（M3 を撤回・性能優先）: global union に非 ASCII 記号が混じると
                # union_keep=None（全件走査）に落ちる。このとき ASCII-only keyword の per-keyword
                # 絞り込みまで行うには restrict_to=None ＝全コーパス rg を keyword×hop ごとに spawn
                # する必要があり、SJIS で日本語識別子を追う本ツールの主用途（60GB・多 keyword・多 hop）
                # でフルコーパス走査が爆発する。得られるのは decode_replaced 診断の帰属精度のみ
                # （TSV は encoding_of を exact relpath でしか読まないため不変・perkw_diag gated）。
                # 性能退行が診断専用の帰属差より有害なため、非 ASCII union 時は FULL のまま許容する
                # （spec §2 の「keyword 横断 DETAIL の逐次版一致は未実現」と同類の既知差）。
                if opts.perkw_diag and opts.use_ripgrep and union_keep is not None:
                    # 探索対象を全コーパス `.` ではなく union_keep に限定する
                    # （keep_k ⊆ union_keep なので結果は同集合・探索空間のみ縮小）。
                    keep_k = _rg.prefilter(source_root, rel_to_abs, sorted(sc | stm),
                                           restrict_to=union_keep)
                    if keep_k is not None:
                        keep_k = keep_k | unsafe_rels
                        kw_results = [r for r in pass_results if r[0] in keep_k]
                    # keep_k is None（非 ASCII 記号 → 全件走査）の場合は FULL のままにする
                absorb_results(st, kw_results, sc, stm, ghop)
            progress.hop(ghop, len(scan_symbols), len(scan_files))
            ghop += 1
        result = {kw: build_indirect_hits(st) for kw, st in states_by_kw.items()}
        progress.done()
        interrupted = False
        return result
    finally:
        if pool is not None:
            if interrupted:
                pool.terminate()      # 中断時は in-flight 完了を待たず即時終了する
            else:
                pool.close()
            pool.join()
        for st in states_by_kw.values():
            try:
                st.edge_store.close()     # ベストエフォートで閉じる（後続 state を守る）
            except Exception:
                pass
        if _auto_cache_dir is not None:
            shutil.rmtree(_auto_cache_dir, ignore_errors=True)   # auto temp の後始末（#9）
