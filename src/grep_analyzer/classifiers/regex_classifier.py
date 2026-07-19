"""SQL/Shell/Perl/Groovy を正規表現で分類する。"""

import re

from grep_analyzer.classifiers.base import ClassifyResult
from grep_analyzer.patterns.literal_masking import mask_literals
from grep_analyzer.patterns.symbol_extraction import GROOVY_LINE_CAP

# Oracle 方言を扱う。_classify_by_rules は先頭一致を優先する。:= を最優先にし、
# WHERE比較→分岐(DECODE/CASE/||)→INSERT/UPDATE代入 の順とする（既存 golden 等価）。
_SQL_RULES = [
    (re.compile(r":="), "代入"),
    (re.compile(r"\bWHERE\b.*?[=<>]", re.IGNORECASE), "比較"),
    (re.compile(r"\bCASE\s+WHEN\b|\bDECODE\s*\(|\|\|", re.IGNORECASE), "分岐"),
    (re.compile(r"\b(?:INSERT|UPDATE)\b", re.IGNORECASE), "代入"),
    # PL/SQL append（出力先頭・宣言/ループ行頭アンカー）
    (re.compile(r"^\s*(?:DBMS_OUTPUT\.PUT_LINE|RAISE_APPLICATION_ERROR)\b", re.IGNORECASE), "出力"),
    (re.compile(r"^\s*(?:CREATE\s+(?:OR\s+REPLACE\s+)?)?"
                r"(?:PROCEDURE|FUNCTION|PACKAGE(?:\s+BODY)?|TRIGGER|TYPE)\b", re.IGNORECASE), "宣言"),
    (re.compile(r"^\s*CURSOR\b", re.IGNORECASE), "宣言"),
    (re.compile(r"\bIF\b.*\bTHEN\b|^\s*ELSIF\b", re.IGNORECASE), "比較"),
    (re.compile(r"^\s*(?:WHILE|FOR)\b|\bLOOP\s*$", re.IGNORECASE), "分岐"),
]
_SHELL_RULES_BOURNE = [
    # == は比較であり代入ではない。抽出側 BOURNE_ASSIGN_RE の =(?!=) と一致させる（H3）。
    # 接頭辞（export/local/declare/typeset）も抽出側と揃える（片側だけだと
    # `export PATH=...` が「その他」なのに chaser は var 抽出する非対称になる）。
    (re.compile(r"^\s*(?:(?:export|local|declare|typeset)\s+(?:-\w+\s+)*)?\w+=(?!=)"), "代入"),
    (re.compile(r"\[\s+.+?(?:=|==|-eq)\s+.+?\]"), "比較"),
    (re.compile(r"^\s*case\s+"), "分岐"),
]
# C系シェルを扱う。代入: set V=/setenv V/@ V=、比較: if(/while(、分岐: switch(/case ...:/breaksw
_SHELL_RULES_CSHELL = [
    (re.compile(r"^\s*(?:set\s+\w+\s*=|setenv\s+\w+|@\s+\w+\s*=)"), "代入"),
    (re.compile(r"^\s*(?:if|while)\s*\("), "比較"),
    (re.compile(r"^\s*switch\s*\(|^\s*case\s+.+:|^\s*breaksw\b"), "分岐"),
]


def _classify_by_rules(rules, line: str) -> ClassifyResult:
    for pat, cat in rules:
        if pat.search(line):
            return (cat, "medium")
    return ("その他", "medium")


# コメントカテゴリを判定する。行頭アンカーで純コメント行のみを対象とする（コードと同居する行はコード優先）。
# Oracle ヒント句 /*+ ... */ ・ --+ ... は最適化指示のためコメントから除外する（(?!\+)）。
_SQL_COMMENT = re.compile(r"^\s*--(?!\+)|^\s*/\*(?!\+).*\*/\s*$")
_SHELL_COMMENT = re.compile(r"^\s*#")
_PERL_COMMENT = re.compile(r"^\s*#")
_GROOVY_COMMENT = re.compile(r"^\s*//|^\s*/\*.*\*/\s*$")

_BLOCK_COMMENT_CACHE_KEY = "_block_comment_lines"

# ブロックコメント状態機械が扱う文字列デリミタ（/* を文字列内で開始扱いしないため）。
_STRING_QUOTES = {"sql": "'", "groovy": "'\""}


def _block_comment_lines(language: str, text: str) -> frozenset[int]:
    """全非空白内容が /* */ ブロックコメント内にある行番号（1始まり）集合を返す。

    行単位 regex は行跨ぎの /* */ を判定できず、開始行・中間行のコメント本文の
    単語（UPDATE/INSERT/if 等）で分類規則が発火する。文字列（SQL '' / Groovy '\"'）
    と行コメント（-- / //）を考慮した 1 パス状態機械で決定的に判定する。
    Oracle ヒント句 /*+ はコメント扱いしない（ブロックは追跡するが行を印しない）。
    既知境界: Groovy の triple-quote／slashy string は未対応（行単位 mask と同じ）。
    """
    quotes = _STRING_QUOTES.get(language, "'")
    line_comment = "--" if language == "sql" else "//"
    comment_only: set[int] = set()
    lineno = 1
    in_block = False
    hint_block = False                        # /*+ ブロック（コメント扱いしない）
    in_string: str | None = None
    has_code = False                          # 行にコメント外の非空白があるか
    has_any = False                           # 行に非空白があるか
    i, n = 0, len(text)
    while i <= n:
        ch = text[i] if i < n else "\n"       # 末尾を仮想改行で行確定する
        if ch == "\n":
            if has_any and not has_code:
                comment_only.add(lineno)
            lineno += 1
            has_code = False
            has_any = False
            in_string = None                  # 行単位 mask と同様、文字列は行内で閉じる前提
            i += 1
            continue
        if not ch.isspace():
            has_any = True
        if in_block:
            if ch == "*" and text[i:i + 2] == "*/":
                in_block = False
                hint_block = False
                i += 2
                continue
            if hint_block and not ch.isspace():
                has_code = True               # ヒント句はコード扱い
            i += 1
            continue
        if in_string is not None:
            has_code = True
            if language == "sql" and ch == "'" and text[i:i + 2] == "''":
                i += 2
                continue
            if language == "groovy" and ch == "\\":
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in quotes:
            in_string = ch
            has_code = True
            i += 1
            continue
        if text[i:i + 2] == line_comment:
            # 行コメントは行末まで読み飛ばす（コメント内の /* を開始扱いしない）。
            while i < n and text[i] != "\n":
                i += 1
            continue
        if text[i:i + 2] == "/*":
            in_block = True
            hint_block = text[i:i + 3] == "/*+"
            if hint_block:
                has_code = True
            i += 2
            continue
        if not ch.isspace():
            has_code = True
        i += 1
    return frozenset(comment_only)


def _in_block_comment(language: str, text, lineno, cache) -> bool:
    """lineno 行がブロックコメント専用行かを file 単位 cache 付きで判定する。"""
    if text is None or lineno is None:
        return False
    if cache is None:
        return lineno in _block_comment_lines(language, text)
    key = (_BLOCK_COMMENT_CACHE_KEY, language)
    if key not in cache:
        cache[key] = _block_comment_lines(language, text)
    return lineno in cache[key]


def classify_sql(line: str, text: str | None = None, lineno: int | None = None,
                 cache: dict | None = None) -> ClassifyResult:
    """SQL行（Oracle方言）を分類する（confidence=medium／コメントは low・内部 mask）。

    text/lineno を渡すと行跨ぎ /* */ ブロックコメントの内部行もコメント判定する。
    """
    if _SQL_COMMENT.match(line) or _in_block_comment("sql", text, lineno, cache):
        return ("コメント", "low")
    return _classify_by_rules(_SQL_RULES, mask_literals("sql", line))


def classify_shell(line: str, dialect: str = "bourne") -> ClassifyResult:
    """Shell行を分類する（confidence=medium／コメントは low・内部 mask）。

    dialect="cshell" のとき csh/tcsh 規則を、それ以外（既定）は bourne 規則を用いる。
    """
    if _SHELL_COMMENT.match(line):
        return ("コメント", "low")
    rules = _SHELL_RULES_CSHELL if dialect == "cshell" else _SHELL_RULES_BOURNE
    return _classify_by_rules(rules, mask_literals("shell", line))


# Perl 規則（先頭一致優先）。比較の裸 < > は -> / => / <= >= を除外する。
_PERL_RULES = [
    (re.compile(r"^\s*sub\s+\w+|\bpackage\s+\w+|\buse\s+constant\b"), "宣言"),
    (re.compile(r"^\s*(?:my|our|local|state)\s+[$@%]|[$@%]\w+\s*=(?![=~>])"), "代入"),
    (re.compile(r"\b(?:if|unless|elsif)\b|==|!=|<=|>=|\beq\b|\bne\b|\blt\b|\bgt\b|\ble\b|"
                r"\bge\b|=~|!~|(?<![-=])<(?!=)|(?<![-=])>(?!=)"), "比較"),
    (re.compile(r"\b(?:for|foreach|while|until)\b"), "分岐"),
    (re.compile(r"\b(?:print|printf|say|warn|die)\b"), "出力"),
]
# Groovy 規則（先頭一致優先）。規則1の def はメソッド宣言形 `def name(` に限定する。
# 型付きメソッド宣言（`List<String> getNames() {`）は行末 `{` を要求し、キーワード
# 始まり（return foo(1) 等）を除外して過剰一致を防ぐ。
_GROOVY_RULES = [
    (re.compile(r"^\s*(?:class|interface|enum|trait)\s+|"
                r"^\s*(?:[\w.<>,\s]+\s+)?def\s+\w+\s*\(|"
                r"^\s*(?!(?:return|if|for|while|switch|new|throw|else|assert|case|catch)\b)"
                r"[\w.]+(?:<[^<>]{0,100}>)?(?:\[\])?\s+\w+\s*\([^()]*\)\s*\{\s*$"), "宣言"),
    (re.compile(r"^\s*(?:def|final|[A-Za-z_]\w*(?:<[^>]*>)?)\s+\w+\s*=(?!=)|"
                r"\b\w+\s*=(?!=)"), "代入"),
    (re.compile(r"\b(?:if|while)\b|==~|<=>|==|!=|<=|>=|=~|"
                r"(?<![-=])<(?!=)|(?<![-=])>(?!=)"), "比較"),
    (re.compile(r"\b(?:switch|for|case)\b"), "分岐"),
    (re.compile(r"\breturn\b"), "return"),
    (re.compile(r"\b(?:println|print|printf)\b|\blog\.\w+"), "出力"),
]


def classify_perl(line: str) -> ClassifyResult:
    """Perl行を分類する（confidence=medium／コメントは low・内部 mask）。"""
    if _PERL_COMMENT.match(line):
        return ("コメント", "low")
    return _classify_by_rules(_PERL_RULES, mask_literals("perl", line))


def classify_groovy(line: str, text: str | None = None, lineno: int | None = None,
                    cache: dict | None = None) -> ClassifyResult:
    """Groovy行を分類する（confidence=medium／コメントは low・内部 mask）。

    text/lineno を渡すと行跨ぎ /* */ ブロックコメントの内部行もコメント判定する。
    """
    line = line[:GROOVY_LINE_CAP]
    if _GROOVY_COMMENT.match(line) or _in_block_comment("groovy", text, lineno, cache):
        return ("コメント", "low")
    return _classify_by_rules(_GROOVY_RULES, mask_literals("groovy", line))
