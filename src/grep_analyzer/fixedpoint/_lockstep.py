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

from pathlib import Path

from grep_analyzer import ripgrep as _rg
from grep_analyzer.fixedpoint._budget_control import (
    apply_global_cap,
    compute_nchunks_union,
    maybe_spill,
)
from grep_analyzer.fixedpoint._finalize import build_indirect_hits
from grep_analyzer.fixedpoint._ingest import absorb_results
from grep_analyzer.fixedpoint._scan import make_file_cache, make_pool, scan_hop
from grep_analyzer.progress import Progress


def run_fixedpoint_multi(states_by_kw, source_root, opts, *, files,
                         unsafe_rels=None, enc_memo=None):
    """全 keyword を lock-step で前進させ keyword 別 indirect Hit を返す。"""
    source_root = Path(source_root)
    unsafe_rels = unsafe_rels or set()
    rel_to_abs = {r: a for r, a in files}
    for st in states_by_kw.values():
        st.rel_to_abs = rel_to_abs
        st.enc_memo = enc_memo          # finalize が st.enc_memo を使う
    progress = Progress(opts.progress)
    progress.start(len(files))
    from grep_analyzer.spill import cleanup_stale_edge_files
    cleanup_stale_edge_files(opts.spill_dir)
    file_cache = make_file_cache()
    pool = make_pool(opts)
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
            # 全 state は同じ opts 由来の budget を持つので先頭を取るだけで安全。
            nchunks = compute_nchunks_union(
                list(states_by_kw.values()), scan_symbols,
                opts=opts, budget=next(iter(states_by_kw.values())).budget)
            pass_results, n_actual_chunks = scan_hop(
                scan_symbols, scan_files, opts, nchunks,
                file_cache=file_cache, pool=pool, enc_memo=enc_memo,
                progress=progress, hop_no=ghop)
            # automaton_split は共有走査ゆえ global hop ごとに1回（出力中立）。
            # その hop に live 記号（sc|stm）を持つ keyword のみに付与する
            # （逐次版で走査しない kw は automaton_split を記録しないため）。
            if nchunks > 1:
                for kw, st in states_by_kw.items():
                    sc_k, stm_k = per_kw[kw]
                    if sc_k or stm_k:
                        st.diagnostics.add(
                            "automaton_split", f"hop={ghop} chunks={n_actual_chunks}")
            # per-keyword decode_replaced/encoding_of 帰属。
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
                if opts.use_ripgrep and union_keep is not None:
                    # 探索対象を全コーパス `.` ではなく union_keep に限定する
                    # （keep_k ⊆ union_keep なので結果は同集合・探索空間のみ縮小）。
                    keep_k = _rg.prefilter(source_root, rel_to_abs, sorted(sc | stm),
                                           restrict_to=union_keep)
                    if keep_k is not None:
                        keep_k = keep_k | unsafe_rels
                        kw_results = [r for r in pass_results if r[0] in keep_k]
                    # keep_k is None（非 ASCII 記号 → 全件走査）の場合は FULL のまま
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
                pool.terminate()      # 中断時は in-flight 完了を待たず即時終了
            else:
                pool.close()
            pool.join()
        for st in states_by_kw.values():
            try:
                st.edge_store.close()     # ベストエフォート（後続 state を守る）
            except Exception:
                pass
