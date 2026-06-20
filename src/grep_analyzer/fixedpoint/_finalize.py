"""scan ループ終了後に indirect Hit 列を構築する。

edge_store の (parent, child) を graph に追加し、終端 Occurrence ごとに
chain_to を列挙して indirect Hit を生成する。seed と同じ (relpath, lineno) は
除外する（seed は direct 側で既に出力されている）。
"""

from grep_analyzer.classify import classify_hit
from grep_analyzer.fixedpoint._scan import file_meta, meta_via_decode_cache, read_bytes_with_sig
from grep_analyzer.fixedpoint._state import ChaseState
from grep_analyzer.model import Hit
from grep_analyzer.provenance import Occurrence
from grep_analyzer.snippet import build_snippet

_REF_KIND = {"constant": "indirect:constant", "var": "indirect:var",
             "getter": "indirect:getter", "setter": "indirect:setter"}


def _uncapped_edges(state: ChaseState):
    """capped シンボルを端点に持たないエッジ列を 1 度だけ materialize する。

    #G: capped は scan 除外だけでなく provenance からも一貫排除する。従来は child が
    capped のエッジは finalize の done 判定で落ちる一方、parent が capped のエッジは
    graph に残り chain に現れる非対称があった。両端で除外して揃える。
    #N: sorted_unique() を 2 度呼ぶと spill 時にスピルファイルのディスク再パースと
    sorted(set(...)) が二重化する。1 度だけ評価して使い回す。
    """
    cap = state.capped
    return [(p, c) for p, c in state.edge_store.sorted_unique()
            if p.symbol not in cap and c.symbol not in cap]


def build_indirect_hits(state: ChaseState) -> list[Hit]:
    """edge_store を走査し indirect Hit 列を決定的に構築する。"""
    opts = state.options
    diag = state.diagnostics
    edges = _uncapped_edges(state)
    for p, c in edges:
        state.graph.add_edge(p, c)

    indirect: list[Hit] = []
    seen: set[Occurrence] = set()
    line_cache: dict[str, list[str]] = {}
    file_meta_by_relpath: dict[str, tuple[str, str, str]] = {}
    for _, c in edges:
        if c in seen or c.symbol not in (state.chase_done | state.terminal_done):
            continue
        if state.graph.is_seed_location(c.relpath, c.lineno):
            continue
        seen.add(c)
        if c.relpath not in line_cache:
            if c.relpath in state.rel_to_abs:
                abspath = state.rel_to_abs[c.relpath]
                raw, sig = read_bytes_with_sig(abspath)   # read 時 sig で put（L1）
                text, enc, replaced, lang, dialect = meta_via_decode_cache(
                    state.enc_memo, state.decode_cache, str(abspath), c.relpath, raw,
                    opts.lang_map, list(opts.encoding_fallback),
                    fast=opts.fast_encoding, sig=sig)
            else:
                # relpath 未知＝abspath が無い。空 bytes の meta を直接生成する（memo 不要）。
                text, enc, replaced, lang, dialect = file_meta(
                    c.relpath, b"", opts.lang_map,
                    fallback_chain=list(opts.encoding_fallback),
                    fast=opts.fast_encoding)
            line_cache[c.relpath] = text.split("\n")
            file_meta_by_relpath[c.relpath] = (text, lang, dialect)
            state.encoding_of.setdefault(c.relpath, (enc, replaced))
        text, language, dialect = file_meta_by_relpath[c.relpath]
        # occurrence 単位の使い捨てパース木キャッシュ：同一 occurrence の classify_hit と
        # build_snippet（および全 chain）が 1 度のパースを共有する。occurrence をまたいで
        # 木を常駐させない（メモリは常時 1 木分）。sorted_unique は (symbol,relpath,lineno) 順
        # なので relpath がまとまらず、relpath 単位常駐にしても局所性がないため使い捨てで十分である。
        tree_cache: dict = {}
        lines = line_cache[c.relpath]
        line = lines[c.lineno - 1] if 0 <= c.lineno - 1 < len(lines) else ""
        kind = state.symbol_kind.get(c.symbol, "var")
        cat, conf = classify_hit(language, dialect, text, c.lineno, line, cache=tree_cache)
        if kind in ("getter", "setter"):
            conf = "low"
        enc, replaced = state.encoding_of.get(c.relpath, ("utf-8", False))
        # snippet は (language, text, lineno) のみに依存し chain 非依存なので、
        # occurrence 単位で 1 回だけ切り出して全 chain で共有する。
        snippet = build_snippet(language, dialect, text, c.lineno, cache=tree_cache)
        for chain in state.graph.chains_to(c, max_depth=opts.max_depth,
                                           max_paths=opts.max_paths, diag=diag):
            indirect.append(Hit(
                keyword=state.keyword, language=language, file=c.relpath,
                lineno=c.lineno, ref_kind=_REF_KIND[kind], category=cat,
                category_sub="", usage_summary=f"{cat} ({language})",
                via_symbol=c.symbol, chain=chain,
                snippet=snippet,
                encoding=enc + (" 要確認" if replaced else ""),
                confidence=conf))
    return indirect
