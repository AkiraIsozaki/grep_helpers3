"""非致命の診断を集約する。先頭にカテゴリ別件数サマリを置き、続いて詳細を並べる。"""

from collections import Counter, defaultdict

SECTION_8_4_CATEGORIES = frozenset({"symbol_rejected", "getter_setter_no_expand"})

# カテゴリごとの詳細保持上限。カウント(_counts)は常に全件正確だが、
# 明細(_detail)はこの件数で頭打ちにして OOM を防ぐ。実運用・全テストでは到達しない高さに設定している。
# render の縮約（detail_limit）とは独立である。
_MAX_RETAINED = 200_000


def _is_exempt(cat: str, exempt=SECTION_8_4_CATEGORIES) -> bool:
    """全件性カテゴリ（縮約免除）か判定する。prov_ プレフィックスも対象。

    縮約免除判定の唯一の実装（render はここに委譲）。
    """
    return cat in exempt or cat.startswith("prov_")


class Diagnostics:
    """カテゴリ別に診断メッセージを蓄積し、サマリ＋詳細で描画する。"""

    def __init__(self) -> None:
        self._counts: Counter = Counter()
        self._detail: dict[str, list[str]] = defaultdict(list)

    def add(self, category: str, message: str) -> None:
        """1件の診断を記録する（カウントは全件、明細は _MAX_RETAINED 件で頭打ち）。"""
        self._counts[category] += 1
        lst = self._detail[category]
        if len(lst) < _MAX_RETAINED:
            lst.append(message)

    def merge_in_order(self, others) -> None:
        """複数 Diagnostics を与えた順でカテゴリ別 detail を連結し件数を合算する。

        counts は全件正確（_counts 加算）。detail は _MAX_RETAINED を尊重して extend
        （超過分は捨て、render の retained 行で表現）。逐次版の追記順（A 全部→B 全部）を再現。
        """
        for other in others:
            for cat, cnt in other._counts.items():
                self._counts[cat] += cnt
            for cat, msgs in other._detail.items():
                lst = self._detail[cat]
                room = _MAX_RETAINED - len(lst)
                if room > 0:
                    lst.extend(msgs[:room])

    def counts(self) -> dict[str, int]:
        """カテゴリ別の総件数（全件正確）。"""
        return dict(self._counts)

    def render(self, detail_limit: int = 0, exempt=None) -> str:
        """診断出力スキーマに従って描画する。detail_limit=0 は無制限＝保持上限内なら現行と完全同一。"""
        is_exempt = (lambda c: _is_exempt(c, exempt)) \
            if exempt is not None else (lambda c: False)  # prov_ ロジック単一源
        out = ["# summary"]
        for cat in sorted(self._counts):
            out.append(f"{cat}\t{self._counts[cat]}")   # 常に真総数
        out.append("# detail")
        for cat in sorted(self._detail):
            msgs = self._detail[cat]
            total = self._counts[cat]                    # 真総数（保持上限で msgs より大のことあり）
            if detail_limit > 0 and not is_exempt(cat) and total > detail_limit:
                # 真総数は常に summary セクション（上の {cat}\t{count}）に出るため、
                # detail_limit 経路でも件数は失われない。_MAX_RETAINED 由来の保持上限は
                # detail_limit < _MAX_RETAINED である限り表示件数に影響せず（先に detail_limit
                # で頭打ち）、"more"/"total" も真総数基準なので過少表示にならない（M・確認済み）。
                for msg in msgs[:detail_limit]:
                    out.append(f"{cat}\t{msg}")
                out.append(f"{cat}\t(... {total - detail_limit} more, {total} total)")
            else:
                for msg in msgs:
                    out.append(f"{cat}\t{msg}")
                if total > len(msgs):                    # 保持上限で落ちた明細を明示
                    out.append(f"{cat}\t(... retained cap {_MAX_RETAINED}, {total} total)")
        return "\n".join(out) + "\n"
