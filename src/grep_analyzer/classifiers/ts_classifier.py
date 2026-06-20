"""tree-sitter で Java/C/Pro*C 等を分類する。py-tree-sitter 0.23 API に依存する。

parse／走査の基盤は ast_base に分離した。本モジュールは direct 行の分類
（classify_ts）とノード型→カテゴリの対応表のみを持つ。
"""

from grep_analyzer.classifiers.ast_base import _ParseFailed, node_at_line, parse_tree
from grep_analyzer.classifiers.base import ClassifyResult

# ノード型 → カテゴリの対応であり、判定軸の最小集合とする。
# 内側から外へ climb して最初に一致した文レベルノードを採る。
# argument_list / init_declarator は if/宣言 と包含関係で衝突するため含めない。
_CATEGORY_JAVAC = {
    "if_statement": "比較",
    "switch_statement": "分岐",
    "switch_expression": "分岐",
    "field_declaration": "宣言",
    "local_variable_declaration": "宣言",
    "declaration": "宣言",
    "preproc_def": "宣言",
    "assignment_expression": "代入",
    "return_statement": "return",
}
_CATEGORY_PY = {
    "if_statement": "比較",
    "match_statement": "分岐",
    "assignment": "代入",
    "augmented_assignment": "代入",
    "return_statement": "return",
    "import_statement": "宣言",
    "import_from_statement": "宣言",
}
_CATEGORY_JS = {
    "if_statement": "比較",
    "switch_statement": "分岐",
    "lexical_declaration": "宣言",
    "variable_declaration": "宣言",
    "field_definition": "宣言",
    "import_statement": "宣言",
    "assignment_expression": "代入",
    "augmented_assignment_expression": "代入",
    "return_statement": "return",
}
_CATEGORY_TS = {
    **_CATEGORY_JS,
    "enum_declaration": "宣言",
    "interface_declaration": "宣言",
    "type_alias_declaration": "宣言",
    "public_field_definition": "宣言",
}
_CATEGORY_BY_LANG = {
    "java": _CATEGORY_JAVAC, "c": _CATEGORY_JAVAC, "proc": _CATEGORY_JAVAC,
    "jsp": _CATEGORY_JAVAC, "angular": _CATEGORY_TS, "angular_inline": _CATEGORY_TS,
    "python": _CATEGORY_PY, "javascript": _CATEGORY_JS,
    "typescript": _CATEGORY_TS, "tsx": _CATEGORY_TS,
}


def classify_ts(language: str, source: str, lineno: int,
                cache: dict | None = None, diag=None) -> ClassifyResult:
    """ファイルを AST 解析して対象行を分類する。

    `cache` を渡すとパース木をメモ化し、同一ファイルの別行・snippet と木を共有できる。
    parse() 失敗時は ("その他","low") に降格し、diag があれば ts_parse_failed を記録する。
    """
    try:
        root = parse_tree(language, source, cache=cache)
    except _ParseFailed:
        if diag is not None:
            diag.add("ts_parse_failed", language)
        return ("その他", "low")
    node = node_at_line(root, lineno)
    # コメント専用行（最小ノードが comment）は climb 前に短絡する。
    # java=line_comment/block_comment、他=comment を endswith で一律カバーする。
    if node is not None and node.type.endswith("comment"):
        return ("コメント", "low")
    while node is not None:
        cat = _CATEGORY_BY_LANG[language].get(node.type)
        if cat is not None:
            return (cat, "high")
        node = node.parent
    return ("その他", "high")
