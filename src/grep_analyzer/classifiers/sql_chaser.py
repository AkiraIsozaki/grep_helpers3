"""SQL (Oracle PL/SQL) 用 Chaser — シンボル抽出とリテラルマスク。

PL/SQL 宣言 `name [CONSTANT] TYPE := …` では型名でなく先頭 id を採る。
通常代入 `x := y`・複数代入 `a:=1;b:=2` は全左辺を保持する。
CONSTANT は constant、それ以外は var に振り分ける。getter/setter は空とする。
バインド `:v`／置換 `&v` は lookbehind で除外する。
`_CHASERS["sql"]` 経由で呼び出す。
"""

from grep_analyzer.model import ChaseSymbols, dedup_symbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import (
    ORACLE_CONSTANT_RE,
    ORACLE_DECL_ASSIGN_RE,
)


def mask(line: str) -> str:
    """SQL のリテラル / コメントを同字数空白に置換する。"""
    pattern = MASK_PATTERNS["sql"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def _extract_var_symbols(dialect: str, line: str) -> list[str]:
    """行から PL/SQL `:=` の左辺（宣言形は先頭 id）を抽出する。

    型付き宣言 `name TYPE := …` では型名でなく先頭 id を採る。
    通常代入/複数代入は全左辺を保持する。バインド `:v`／置換 `&v` は除外する。
    """
    return [m.group(1) for m in ORACLE_DECL_ASSIGN_RE.finditer(line)]


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に SQL(Oracle/PL-SQL) の規則で分類抽出する（dialect 無視）。

    const/var 抑止・出現順 uniq は dedup_symbols に委譲する（全 chaser 共通）。
    """
    masked = mask(line)
    consts = [m.group(1) for m in ORACLE_CONSTANT_RE.finditer(masked)]
    vars_ = _extract_var_symbols(dialect, masked)
    return dedup_symbols(consts, vars_, (), ())
