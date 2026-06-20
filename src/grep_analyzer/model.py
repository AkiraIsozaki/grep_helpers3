"""ドメインモデル（ChaseSymbols/Hit）とTSVスキーマ・決定的ソート・chaser 共有ヘルパを提供する。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChaseSymbols:
    """1 行から抽出した追跡候補を表す。

    `constants` / `vars` は不動点で多ホップ追跡される。
    `getters` / `setters` は横展開せず、全反復で terminal として報告する。
    """

    constants: tuple[str, ...] = ()
    vars: tuple[str, ...] = ()
    getters: tuple[str, ...] = ()
    setters: tuple[str, ...] = ()


def dedup_symbols(constants, vars_, getters, setters) -> ChaseSymbols:
    """出現順を保ちつつ重複を除いて ChaseSymbols を組む。

    1 行複数束縛・連鎖代入の二重取り対策。const に出た名前は vars から落とす
    （定数の方を優先）。各 chaser（python/javascript/typescript）が共有する。
    """
    def ordered_uniq(xs):
        seen = set()
        return tuple(x for x in xs if not (x in seen or seen.add(x)))
    cset = set(constants)
    return ChaseSymbols(ordered_uniq(constants),
                        ordered_uniq(v for v in vars_ if v not in cset),
                        ordered_uniq(getters), ordered_uniq(setters))


TSV_COLUMNS = [
    "keyword", "language", "file", "lineno", "ref_kind",
    "category", "category_sub", "usage_summary", "via_symbol",
    "chain", "snippet", "encoding", "confidence",
]


@dataclass(frozen=True)
class Hit:
    """TSV1行に対応する分類結果を表す（direct / indirect:* を含む）。"""

    keyword: str
    language: str
    file: str
    lineno: int
    ref_kind: str
    category: str
    category_sub: str
    usage_summary: str
    via_symbol: str
    chain: str
    snippet: str
    encoding: str
    confidence: str

    def to_row(self) -> list[str]:
        """TSV_COLUMNS の順で文字列セルのリストを返す。"""
        return [
            self.keyword, self.language, self.file, str(self.lineno),
            self.ref_kind, self.category, self.category_sub,
            self.usage_summary, self.via_symbol, self.chain,
            self.snippet, self.encoding, self.confidence,
        ]


def sort_key(h: Hit) -> tuple:
    """全順序キー。

    (ref_kind_rank, chain_group, file, lineno, ref_kind, via_symbol,
     category, category_sub, confidence, usage_summary, snippet,
     language, encoding)。ref_kind_rank: direct→0 / indirect:*→1。
    chain_group: direct→"" / indirect:*→chain。lineno は数値順で比較する。
    """
    ref_kind_rank = 0 if h.ref_kind == "direct" else 1
    chain_group = "" if h.ref_kind == "direct" else h.chain
    return (
        ref_kind_rank, chain_group, h.file, h.lineno, h.ref_kind,
        h.via_symbol, h.category, h.category_sub, h.confidence,
        h.usage_summary, h.snippet, h.language, h.encoding,
    )
