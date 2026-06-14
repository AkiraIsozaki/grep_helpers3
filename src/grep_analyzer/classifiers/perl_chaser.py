"""Perl 用 Chaser — sigil 付き代入左辺・use constant を抽出する。

sigil（$ @ %）は剥がして bare 識別子を追跡シンボルとする。
getter/setter は型解決依存のため追跡しない。heredoc/POD/任意デリミタ q// は
行単位マスクの対象外である（既知境界）。
`_CHASERS["perl"]` 経由で呼び出す。
"""

from grep_analyzer.model import ChaseSymbols, dedup_symbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import (
    PERL_ASSIGN_RE,
    PERL_USE_CONSTANT_RE,
)


def mask(line: str) -> str:
    """Perl のリテラル / コメントを同字数空白に置換する（$# は壊さない）。"""
    pattern = MASK_PATTERNS["perl"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に Perl の規則で分類抽出する（dialect は無視）。"""
    masked = mask(line)
    consts = [m.group(1) for m in PERL_USE_CONSTANT_RE.finditer(masked)]
    vars_ = [m.group(1) for m in PERL_ASSIGN_RE.finditer(masked)]
    return dedup_symbols(consts, vars_, (), ())
