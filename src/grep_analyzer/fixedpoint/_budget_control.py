"""グローバル cap / spill / nchunks を計算する。

- apply_global_cap: --memory-limit / --max-symbols でシンボル集合を切り詰める。
  決定的（キー: (symbol_hop, len(s), s)）。
- maybe_spill: in-memory edge 数と introducers 数で予算超過を判定し、
  超過時に edge_store.maybe_spill_now() を呼ぶ。diag は 1 度だけ記録。
- compute_nchunks_union: lock-step 共有エンジンの union 予算版。1 hop の chunk 数を
  予算と force_chunks から決める（chase_active/terminal_active を空にした直後に呼ぶ前提）。
"""

from grep_analyzer import budget as _budget
from grep_analyzer.fixedpoint._state import ChaseState


def apply_global_cap(state: ChaseState):
    """シンボル集合を memory_limit / max_symbols で決定的に絞り込む。"""
    diag = state.diagnostics
    opts = state.options
    live = sorted(state.chase_active | state.chase_done
                  | state.terminal_active | state.terminal_done,
                  key=lambda s: (state.symbol_hop.get(s, 0), len(s), s))
    keep_count = opts.max_symbols
    if not state.budget.unlimited:
        while keep_count > 0 and state.budget.exceeded(_budget.estimate_items(
                n_symbols=keep_count, n_edges=0, n_intro=keep_count)):
            keep_count -= 1
    if len(live) <= keep_count:
        return
    for s in live[keep_count:]:
        if s not in state.capped:
            diag.add("symbol_rejected", f"capped\t{s}")
            state.capped.add(s)
        # 既 capped でも discard は冪等である。直前 hop で active になっていた可能性があるため
        # 両 set から確実に除外する。
        state.chase_active.discard(s)
        state.terminal_active.discard(s)


def maybe_spill(state: ChaseState, hop: int):
    """予算超過時に edge_store を spill する（1 度だけ diag 記録）。"""
    if state.budget.unlimited or state.edge_store.spilled:
        return
    n_intro = sum(len(v) for v in state.introducers.values())
    n_live = len(state.chase_active | state.chase_done
                 | state.terminal_active | state.terminal_done)
    if state.budget.exceeded(_budget.estimate_items(
            n_symbols=n_live, n_edges=state.edge_store.in_memory_len(),
            n_intro=n_intro)):
        state.edge_store.maybe_spill_now()
        if not state.spill_logged:
            state.diagnostics.add("graph_spilled", f"hop={hop}")
            state.spill_logged = True


def compute_nchunks_union(states, union_symbols, *, opts, budget) -> int:
    """lock-step 共有エンジンの union 予算版 nchunks を返す。

    複数 state にまたがる集計量で chunk 数を決める:
    n_live=len(union_symbols)（その hop の union 記号数）、
    n_intro=Σ_states Σ introducers、in_memory_len=Σ_states edge_store.in_memory_len()。
    budget/opts は明示注入する。

    finite --memory-limit かつ hop≥2 では旧逐次版と chunk 数・automaton_split 診断が
    異なり得るが、automaton_split は出力中立で chunking も TSV 不変である。
    """
    nchunks = 1
    if opts.force_chunks and opts.force_chunks > 1:
        return min(opts.force_chunks, opts.max_passes, max(1, len(union_symbols)))
    if budget.unlimited:
        return 1
    n_intro = sum(sum(len(v) for v in st.introducers.values()) for st in states)
    in_memory_len = sum(st.edge_store.in_memory_len() for st in states)
    n_live = len(union_symbols)
    if not budget.exceeded(_budget.estimate_items(
            n_symbols=n_live, n_edges=in_memory_len, n_intro=n_intro)):
        return 1
    while nchunks < opts.max_passes and nchunks < len(union_symbols) and \
            budget.exceeded(_budget.estimate_items(
                n_symbols=-(-len(union_symbols) // (nchunks + 1)),
                n_edges=in_memory_len, n_intro=n_intro)):
        nchunks += 1
    return nchunks
