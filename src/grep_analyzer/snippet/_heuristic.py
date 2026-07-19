"""sql/shell/perl/groovy のヒューリスティック span を切り出す。

mask_literals を行ごとに適用し、句境界・文末・shell 終端で停止する。
heredoc は mask 非対応（既知境界）。LINE_MAX で必ず有限停止。
"""

import re

from grep_analyzer.chase import mask_literals
from grep_analyzer.patterns.snippet_boundaries import (
    GROOVY_TERMINATOR_RE,
    PERL_TERMINATOR_RE,
    SH_TERMINATOR_RE,
    SQL_CLAUSE_RE,
)
from grep_analyzer.snippet._clamp import LINE_MAX


def _balanced(text: str) -> bool:
    bracket_depth = 0
    for c in text:
        if c in "([{":
            bracket_depth += 1
        elif c in ")]}":
            bracket_depth -= 1
    return bracket_depth == 0 and text.count("'") % 2 == 0 and text.count('"') % 2 == 0


def heuristic_span(lines: list[str], hit: int, language: str) -> tuple[int, int]:
    """sql/shell/perl/groovy の決定的境界を返す。mask_literals で誤爆を防ぐ。

    ヒット行自身は停止判定しない。各方向1行ずつ移動し、停止条件を満たした行で停止する。
    停止条件: 行末 \\ 無・括弧/クォートバランス・SQL は ; か句境界・shell は fi/done/esac 等。
    """
    # stop() が参照するのはヒット ±(LINE_MAX-1) の窓だけ（上下とも最大 LINE_MAX-1 行移動）。
    # 旧実装は全行を mask し、ヒットごと呼ばれるため O(ヒット数×ファイルサイズ) だった（M1）。
    # 窓外を mask しても結果に使われないので、窓内のみ mask して出力はバイト不変。
    lo = max(0, hit - (LINE_MAX - 1))
    hi = min(len(lines) - 1, hit + (LINE_MAX - 1))
    masked_lines = {i: mask_literals(language, lines[i]) for i in range(lo, hi + 1)}

    def _is_stoppable(x: str) -> bool:
        return not x.rstrip().endswith("\\") and _balanced(x)

    def _is_terminator(x: str) -> bool:
        """文/ブロックの終端行か（上方向では前文の終端＝span に含めない）。"""
        if language == "sql":
            return x.rstrip().endswith(";")
        if language == "perl":
            return bool(PERL_TERMINATOR_RE.search(x))
        if language == "groovy":
            return bool(GROOVY_TERMINATOR_RE.search(x))
        return bool(SH_TERMINATOR_RE.search(x))   # shell（既定）

    def stop(i: int) -> bool:
        x = masked_lines[i]
        if not _is_stoppable(x):
            return False
        if language == "sql" and SQL_CLAUSE_RE.search(x):
            return True
        return _is_terminator(x)

    def _upward_boundary(x: str):
        """上方向の停止種別を返す。"include"＝現文/現ブロックの頭（含めて停止）、
        "exclude"＝前文の終端（含めず停止）、None＝続行。"""
        if language == "sql":
            if x.rstrip().endswith(";"):
                return "exclude"
            return "include" if SQL_CLAUSE_RE.search(x) else None
        if language == "perl":
            if re.match(r"\s*sub\b", x):
                return "include"
            return "exclude" if PERL_TERMINATOR_RE.search(x) else None
        if language == "groovy":
            if re.match(r"\s*(?:class|def)\b", x):
                return "include"
            return "exclude" if GROOVY_TERMINATOR_RE.search(x) else None
        # shell: `if ...; then` / `for ...; do` は現ブロックの頭（`;` を含むが開き行）。
        if re.search(r"\b(?:then|do|else)\s*$", x.rstrip()):
            return "include"
        return "exclude" if SH_TERMINATOR_RE.search(x) else None

    # 上方向: 終端行（前文の `;` / fi 等）は現文に属さないため span に含めず停止する。
    # 開き行（SQL 句頭・shell の then/do・perl sub・groovy class/def）は現文の頭なので
    # 含めて停止する（下方向と非対称）。
    span_start = hit
    for _ in range(LINE_MAX - 1):
        if span_start == 0:
            break
        cand = span_start - 1
        x = masked_lines[cand]
        if _is_stoppable(x):
            boundary = _upward_boundary(x)
            if boundary == "exclude":
                break
            if boundary == "include":
                span_start = cand
                break
        span_start = cand
    span_end = hit
    for _ in range(LINE_MAX - 1):
        if span_end == len(lines) - 1:
            break
        span_end += 1
        if stop(span_end):
            break
        if (span_end - span_start + 1) >= LINE_MAX:
            break
    return span_start, span_end
