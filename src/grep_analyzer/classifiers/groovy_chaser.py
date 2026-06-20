"""Groovy 用 Chaser — final 定数と def/型付き変数代入を抽出する。

final（static 任意）を constant、それ以外の代入左辺を var とする。
getter/setter は型解決依存のため追跡しない。`obj.field=` の限定子剥がし・
複数行 GString・slashy string は既知の境界である。
`_CHASERS["groovy"]` 経由で呼び出す。
"""

from grep_analyzer.model import ChaseSymbols, dedup_symbols
from grep_analyzer.patterns.literal_masking import mask_literals
from grep_analyzer.patterns.symbol_extraction import (
    GROOVY_CONST_RE,
    GROOVY_VAR_RE,
    GROOVY_LINE_CAP,
)


def mask(line: str) -> str:
    """Groovy のリテラル / コメントを同字数空白に置換する。"""
    return mask_literals("groovy", line)


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に Groovy の規則で分類抽出する（dialect は無視）。"""
    line = line[:GROOVY_LINE_CAP]
    masked = mask(line)
    consts = [g.group(2) for g in GROOVY_CONST_RE.finditer(masked)
              if "final" in g.group(1).split()]
    vars_ = [m.group(1) for m in GROOVY_VAR_RE.finditer(masked)]
    return dedup_symbols(consts, vars_, (), ())
