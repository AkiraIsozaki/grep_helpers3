"""決定的メモリ近似。RSS でなくアイテム数の決定的近似で来歴グラフ等のメモリを見積もり、
--memory-limit を degrade の決定的トリガに換算する。同一入力・同一 limit なら同一の判断を下す。
"""

# 1 MB あたりの近似アイテム上限（固定定数＝決定的換算）。実バイト精度は perf の領分とする。
# snippet 多行化により 1 レコード最大バイトが増加したため再較正済み（130084→74044）。
_ITEMS_PER_MB = 74044


def estimate_items(*, n_symbols: int, n_edges: int, n_intro: int) -> int:
    """来歴グラフ常駐の決定的アイテム近似（各概念1件＝固定重み）。"""
    return n_symbols + n_edges + n_intro


class MemoryBudget:
    """--memory-limit(MB) を決定的 item 予算へ換算し超過判定する。

    None=無制限／0=item予算0（priority-1 最大切り捨て＋スピル＋分割）／
    N>0=N*_ITEMS_PER_MB。
    """

    def __init__(self, limit_mb: int | None) -> None:
        self.unlimited = limit_mb is None
        self.item_budget = 0 if limit_mb is None else limit_mb * _ITEMS_PER_MB

    def exceeded(self, n_items: int) -> bool:
        """予算超過か（無制限は常に False・上限ちょうどは可）。"""
        if self.unlimited:
            return False
        return n_items > self.item_budget
