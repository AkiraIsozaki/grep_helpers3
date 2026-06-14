"""Pro*C前処理: EXEC SQL / EXEC ORACLE 区間を行数保存で中立化する。

改行のみ残して空行化することで行番号を不変に保つ（桁ズレは許容）。
"""

import re

from grep_analyzer.patterns.literal_masking import MASK_PATTERNS

# `EXEC SQL ... ;` / `EXEC SQL ... END-EXEC` / `EXEC ORACLE ... ;` を行跨ぎで捕捉する
_EXEC_RE = re.compile(
    r"\bEXEC\s+(?:SQL|ORACLE)\b.*?(?:;|END-EXEC\b)",
    re.IGNORECASE | re.DOTALL,
)


_PROC_LIT_RE = MASK_PATTERNS["proc"]


def _blank_literals(source: str) -> str:
    return _PROC_LIT_RE.sub(
        lambda match: "".join(c if c == "\n" else " " for c in match.group(0)),
        source)


def _exec_char_spans(source: str) -> list[tuple[int, int]]:
    """EXEC SQL/ORACLE 区間を (start_char, end_char) で返す（区間検出の唯一の源）。

    リテラル・コメントを空白化したコピー上で _EXEC_RE を走らせ、文字列内 ;/END-EXEC の
    誤切断を防ぐ。空白化は長さ保存なので原ソースへ正しく写像できる。
    """
    masked = _blank_literals(source)
    return [(m.start(), m.end()) for m in _EXEC_RE.finditer(masked)]


def mask_exec_sql(source: str) -> str:
    """EXEC SQL/ORACLE 区間を中立化する。_exec_char_spans で区間を検出し、
    当該区間を改行のみ残して空行化する（行番号不変）。"""
    out: list[str] = []
    last = 0
    for s, e in _exec_char_spans(source):
        out.append(source[last:s])
        out.append("\n" * source.count("\n", s, e))
        last = e
    out.append(source[last:])
    return "".join(out)


def exec_spans(source: str) -> list[tuple[int, int]]:
    """EXEC SQL/ORACLE 区間を (start_line, end_line)（0始まり）で返す。"""
    return [(source.count("\n", 0, s), source.count("\n", 0, e))
            for s, e in _exec_char_spans(source)]
