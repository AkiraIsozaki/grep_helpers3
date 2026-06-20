"""追跡シンボル抽出 dispatcher。

行ベース（_CHASERS）: shell/sql/perl/groovy。
AST ベース（_AST_CHASERS）: python/javascript/typescript/tsx/angular/java/c/proc/jsp。
public API（extract_var_symbols / mask_literals / extract_chase_symbols）を保ちつつ、
内部実装を各 Chaser に委譲する薄い dispatcher。
"""

from grep_analyzer.classifiers import _AST_CHASERS, _CHASERS
from grep_analyzer.classifiers.shell_chaser import _extract_var_symbols as _shell_extract
from grep_analyzer.classifiers.sql_chaser import _extract_var_symbols as _sql_extract
from grep_analyzer.classifiers.ts_classifier import parse_tree
from grep_analyzer.model import ChaseSymbols

# 行ベース chaser への入力行の最大長である。これを超える行は先頭のみを見る。
# ReDoS を構造的に防ぐ。snippet の _clamp.CHAR_MAX=800 と揃える。
# 通常のソース行長を上回るため出力は実質不変。ただし 8192 等の大きい値では
# GROOVY 正規表現が依然 ReDoS する（実測: 8192字で 60s 超）ため必ず 800 とする。
# automaton 走査（ヒット検出）には適用しないためヒットの取りこぼしは生じない。
_MAX_CHASE_LINE = 800


def extract_var_symbols(language: str, dialect: str, line: str) -> list[str]:
    """1 行から indirect:var 追跡シンボル（代入の左辺識別子）を抽出する。

    左辺識別子のみが必要な呼出元向けに、Chaser を経由せず直接
    `*_chaser._extract_var_symbols` を呼ぶ。対象外言語・該当なしは空リストを返す。
    """
    line = line[:_MAX_CHASE_LINE]
    if language == "sql":
        return _sql_extract(line)          # SQL は dialect 非依存
    if language == "shell":
        return _shell_extract(dialect, line)
    return []


def mask_literals(language: str, line: str) -> str:
    """文字列リテラル・コメントを同字数空白に置換する。

    未登録言語は原行をそのまま返す。
    """
    chaser = _CHASERS.get(language)
    return line if chaser is None else chaser.mask(line)


def extract_chase_symbols(language: str, dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に言語別 Chaser で分類抽出する（決定的・出現順）。

    対象外言語は空の ChaseSymbols を返す。
    """
    line = line[:_MAX_CHASE_LINE]
    chaser = _CHASERS.get(language)
    if chaser is None:
        return ChaseSymbols()
    return chaser.extract(dialect, line)


def extract_chase_symbols_from_root(language: str, root, lineno: int) -> ChaseSymbols:
    """parse 済 root から AST chaser で抽出（worker 用・file 単位1パース共有）。"""
    chaser = _AST_CHASERS.get(language)
    return ChaseSymbols() if chaser is None else chaser.extract_tree(language, root, lineno)


def extract_chase_symbols_tree(language: str, text: str, lineno: int) -> ChaseSymbols:
    """text を parse して AST chaser で抽出（seed/absorb 用）。非 AST 言語/parse 失敗は空。"""
    if language not in _AST_CHASERS:
        return ChaseSymbols()
    from grep_analyzer.classifiers.ts_classifier import _ParseFailed
    try:
        root = parse_tree(language, text)
    except _ParseFailed:
        return ChaseSymbols()
    return extract_chase_symbols_from_root(language, root, lineno)
