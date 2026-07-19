"""scan ループ終了後に indirect Hit 列を構築する。

edge_store の (parent, child) を graph に追加し、終端 Occurrence ごとに
chain_to を列挙して indirect Hit を生成する。seed と同じ (relpath, lineno) は
除外する（seed は direct 側で既に出力されている）。
"""

from collections import OrderedDict

from grep_analyzer.classifiers.regex_classifier import BLOCK_COMMENT_CACHE_KEY
from grep_analyzer.classify import classify_hit
from grep_analyzer.embed_preprocess import SPANS_CACHE_KEY
from grep_analyzer.fixedpoint._scan import file_meta, meta_via_decode_cache, read_bytes_with_sig
from grep_analyzer.fixedpoint._state import ChaseState
from grep_analyzer.model import Hit
from grep_analyzer.provenance import Occurrence
from grep_analyzer.snippet import build_snippet

_REF_KIND = {"constant": "indirect:constant", "var": "indirect:var",
             "getter": "indirect:getter", "setter": "indirect:setter"}

# finalize が常駐させる復号テキストの上限（文字数の概算予算）。scan 側 _FileCache と
# 同じ思想で、ヒットファイル数に比例した無制限常駐（数千ファイル×数MBで数十GB）を防ぐ。
_FINALIZE_TEXT_BUDGET = 64 * 1024 * 1024


def _is_shareable_cache_key(key) -> bool:
    """occurrence 間で共有してよい小物キャッシュキーか（パース木は共有しない）。"""
    return key == SPANS_CACHE_KEY or (
        isinstance(key, tuple) and len(key) == 2 and key[0] == BLOCK_COMMENT_CACHE_KEY)


def _uncapped_edges_iter(state: ChaseState):
    """capped シンボルを端点に持たないエッジ列を streaming で yield する。

    #G: capped は scan 除外だけでなく provenance からも一貫排除する。従来は child が
    capped のエッジは finalize の done 判定で落ちる一方、parent が capped のエッジは
    graph に残り chain に現れる非対称があった。両端で除外して揃える。
    list に materialize しない: 全ユニークエッジの list は graph 隣接と合わせて
    エッジ集合の多重コピーを常駐させ、スピルの目的（メモリ有界）を消費側で
    無効化する。2 パス目はスピル run の再ソート・再マージを伴うが、60GB 級では
    メモリのほうが希少資源である（sorted_unique は決定的なので 2 パスは同一列）。
    """
    cap = state.capped
    for parent, child in state.edge_store.sorted_unique():
        if parent.symbol not in cap and child.symbol not in cap:
            yield parent, child


class _FinalizeFileCache:
    """relpath→(text, lines, language, dialect) の予算つき LRU である。

    sorted_unique は (symbol, relpath, lineno) 順で relpath がまとまらないため、
    無予算 dict だと全ヒットファイルの全文＋行分割が finalize 終了まで常駐する。
    予算超過時は最古参照から捨て、再ヒット時は decode_cache 経由で安価に再構築する。
    診断（source_read_failed）と encoding_of 記録は初回ロード時のみ発火し、
    退避→再ロードで重複しない（従来の無予算 dict と診断件数を揃える）。
    """

    def __init__(self, state: ChaseState, budget: int = _FINALIZE_TEXT_BUDGET) -> None:
        self._state = state
        self._budget = budget
        self._cache: "OrderedDict[str, tuple[str, list[str], str, str]]" = OrderedDict()
        self._total_chars = 0
        self._read_failed_logged: set[str] = set()

    def get(self, relpath: str) -> tuple[str, list[str], str, str, dict]:
        """relpath の (text, lines, language, dialect, aux) を返す（miss は実読で構築）。

        aux は occurrence 間で共有してよい小物キャッシュ（ブロックコメント行集合・
        inline template spans）の置き場。パース木は含めない（メモリ常駐を防ぐ）。
        """
        hit = self._cache.get(relpath)
        if hit is not None:
            self._cache.move_to_end(relpath)
            return hit
        entry = self._load(relpath)
        self._cache[relpath] = entry
        # 行 list は文字を全複製するため常駐は約 2×len(text)。予算はその概算で数える
        # （len(text) のみだと実常駐が予算の数倍になり上限の意味が薄れる）。
        self._total_chars += 2 * len(entry[0])
        while self._total_chars > self._budget and len(self._cache) > 1:
            _, (old_text, _, _, _, _) = self._cache.popitem(last=False)
            self._total_chars -= 2 * len(old_text)
        return entry

    def _load(self, relpath: str) -> tuple[str, list[str], str, str, dict]:
        state = self._state
        opts = state.options
        read_failed = False
        if relpath in state.rel_to_abs:
            abspath = state.rel_to_abs[relpath]
            try:
                # scan 完了後〜finalize の間にファイルが消える TOCTOU。全 hop 走査済みの
                # 最終盤で run を落とさず、空 bytes の meta へ降格して行自体は残す。
                # 空 meta は decode_cache に put しない（消えたファイルの正本化を防ぐ）。
                raw, sig = read_bytes_with_sig(abspath)
            except OSError:
                if relpath not in self._read_failed_logged:
                    state.diagnostics.add("source_read_failed", relpath)
                    self._read_failed_logged.add(relpath)
                read_failed = True
            else:
                text, enc, replaced, lang, dialect = meta_via_decode_cache(
                    state.enc_memo, state.decode_cache, str(abspath), relpath, raw,
                    opts.lang_map, list(opts.encoding_fallback),
                    fast=opts.fast_encoding, sig=sig)
        if relpath not in state.rel_to_abs or read_failed:
            # relpath 未知＝abspath が無い。空 bytes の meta を直接生成する（memo 不要）。
            text, enc, replaced, lang, dialect = file_meta(
                relpath, b"", opts.lang_map,
                fallback_chain=list(opts.encoding_fallback),
                fast=opts.fast_encoding)
        state.encoding_of.setdefault(relpath, (enc, replaced))
        return text, text.split("\n"), lang, dialect, {}


def build_indirect_hits(state: ChaseState) -> list[Hit]:
    """edge_store を走査し indirect Hit 列を決定的に構築する。"""
    opts = state.options
    diag = state.diagnostics
    for p, c in _uncapped_edges_iter(state):
        state.graph.add_edge(p, c)
    state.graph.compact()                     # 重複判定専用 set を解放（以降 add しない）

    indirect: list[Hit] = []
    seen: set[Occurrence] = set()
    file_cache = _FinalizeFileCache(state)
    # done union はループ不変。エッジ毎に再構築すると O(|E|×|S|) になるためホイストする。
    done_symbols = state.chase_done | state.terminal_done
    for _, c in _uncapped_edges_iter(state):
        if c in seen or c.symbol not in done_symbols:
            continue
        if state.graph.is_seed_location(c.relpath, c.lineno):
            continue
        seen.add(c)
        text, lines, language, dialect, aux = file_cache.get(c.relpath)
        # occurrence 単位の使い捨てパース木キャッシュ：同一 occurrence の classify_hit と
        # build_snippet（および全 chain）が 1 度のパースを共有する。occurrence をまたいで
        # 木を常駐させない（メモリは常時 1 木分）。sorted_unique は (symbol,relpath,lineno) 順
        # なので relpath がまとまらず、relpath 単位常駐にしても局所性がないため使い捨てで十分である。
        # ただし O(ファイルサイズ) の小物（ブロックコメント行集合・inline template spans）
        # は aux 経由でファイル単位に共有する（occurrence 毎の全文再走査＝
        # O(hits×filesize) を防ぐ）。
        tree_cache: dict = dict(aux)
        line = lines[c.lineno - 1] if 0 <= c.lineno - 1 < len(lines) else ""
        kind = state.symbol_kind.get(c.symbol, "var")
        cat, conf = classify_hit(language, dialect, text, c.lineno, line, cache=tree_cache)
        if kind in ("getter", "setter"):
            conf = "low"
        enc, replaced = state.encoding_of.get(c.relpath, ("utf-8", False))
        # snippet は (language, text, lineno) のみに依存し chain 非依存なので、
        # occurrence 単位で 1 回だけ切り出して全 chain で共有する。
        snippet = build_snippet(language, dialect, text, c.lineno, cache=tree_cache)
        aux.update((k, v) for k, v in tree_cache.items() if _is_shareable_cache_key(k))
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
