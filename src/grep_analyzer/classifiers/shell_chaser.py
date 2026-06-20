"""Shell 用 Chaser — bourne / cshell 両方言を処理する。

dialect 引数で bourne / cshell を分岐する。
- bourne: 行頭 `var=` の左辺、`readonly var=` で constant 化
- cshell: `set v =` / `setenv V` / `@ v =` の左辺

chase.py の dispatcher が `_CHASERS["shell"]` 経由で呼び出す。
"""

from grep_analyzer.model import ChaseSymbols
from grep_analyzer.patterns.literal_masking import mask_literals
from grep_analyzer.patterns.symbol_extraction import (
    BOURNE_ASSIGN_RE,
    BOURNE_READONLY_RE,
    CSHELL_ASSIGN_RE,
)


def mask(line: str) -> str:
    """Shell のリテラル / コメントを同字数空白に置換する。"""
    return mask_literals("shell", line)


def _extract_var_symbols(dialect: str, line: str) -> list[str]:
    """行から代入左辺を抽出する（dispatcher 向け公開ヘルパ）。

    生行・マスク済み行どちらでも受け付ける。shell の代入規則は行頭アンカーを持つため
    マスク状態に依存しない（桁数保存で行頭位置は不変）。

    dialect=cshell: `set v =` / `setenv V` / `@ v =` の左辺
    dialect=その他: 行頭 `var=` の左辺
    """
    if dialect == "cshell":
        out: list[str] = []
        for m in CSHELL_ASSIGN_RE.finditer(line):
            out.append(next(g for g in m.groups() if g))
        return out
    m = BOURNE_ASSIGN_RE.match(line)
    return [m.group(1)] if m else []


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に shell の規則で分類抽出する。

    bourne: `readonly v=` を constant、それ以外の代入を var
    cshell: 代入をすべて var として収集
    """
    masked = mask(line)
    if dialect != "cshell":
        rm = BOURNE_READONLY_RE.match(masked)
        if rm is not None:
            return ChaseSymbols((rm.group(1),), (), (), ())
    return ChaseSymbols((), tuple(_extract_var_symbols(dialect, masked)), (), ())
