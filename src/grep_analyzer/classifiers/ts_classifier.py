"""tree-sitter による Java/C/Pro*C 分類。py-tree-sitter 0.23 API に依存。"""

# tree-sitter wheel 欠落でも regex トラックを起動可能にするため遅延 import。
# AST 経路（java/c/proc/jsp/angular/angular_inline/python/javascript/typescript/tsx）に
# 初めて到達したときだけ wheel を import する。欠落時は ModuleNotFoundError がその呼出で
# 顕在化し、呼出側 regex 経路は影響を受けない。
from grep_analyzer.classifiers.base import ClassifyResult
from grep_analyzer.embed_preprocess import host_grammar, host_source

_LANGS: dict | None = None


def _ensure_langs() -> dict:
    """tree-sitter grammar を初回アクセス時に構築（遅延）。"""
    global _LANGS
    if _LANGS is None:
        import tree_sitter_c
        import tree_sitter_java
        import tree_sitter_javascript
        import tree_sitter_python
        import tree_sitter_typescript
        from tree_sitter import Language

        _LANGS = {
            "java": Language(tree_sitter_java.language()),
            "c": Language(tree_sitter_c.language()),
            "python": Language(tree_sitter_python.language()),
            "javascript": Language(tree_sitter_javascript.language()),
            "typescript": Language(tree_sitter_typescript.language_typescript()),
            "tsx": Language(tree_sitter_typescript.language_tsx()),
        }
    return _LANGS


# ノード型 → カテゴリ（判定軸の最小集合）。
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


# Parser は grammar ごとに 1 度だけ生成して再利用する（parse は毎回新 Tree を返すので再利用安全）。
# jobs>1 はプロセス並列なので各プロセスが独立した dict を持つ。スレッド共有は無い。
# Parser 型をトップレベルで参照しないため dict アノテーションを緩める（遅延 import と同理由）。
_PARSERS: dict = {}


def _parser(language: str) -> "Parser":
    from tree_sitter import Parser
    grammar = host_grammar(language)
    parser = _PARSERS.get(grammar)
    if parser is None:
        parser = Parser(_ensure_langs()[grammar])
        _PARSERS[grammar] = parser
    return parser


def node_at_line(root, lineno: int):
    """対象行（lineno は 1 始まり）を内包する最小ノードを決定的に返す。

    `(行スパン, start_byte, end_byte, ノード型)` の最小で一意選択（走査順に依存しない全順序）。
    classify_ts と snippet/_ts.py が共有する。
    """
    target = lineno - 1
    best = None
    best_key = None
    cursor = [root]
    while cursor:
        node = cursor.pop()
        if node.start_point[0] <= target <= node.end_point[0]:
            key = (node.end_point[0] - node.start_point[0], node.start_byte, node.end_byte, node.type)
            if best_key is None or key < best_key:
                best, best_key = node, key
            cursor.extend(node.children)
    return best


def binding_at_line(root, lineno: int, binding_types):
    """対象行を内包し binding_types に属する最小スパンノードを決定的に返す。

    node_at_line と同じ全順序キー (行スパン, start_byte, end_byte, 型) で一意選択。
    「最左最小葉から climb」では届かない束縛（例: `class C { get x() {} }`）を
    直接拾うために使う。該当なしは None。
    """
    target = lineno - 1
    best = None
    best_key = None
    cursor = [root]
    while cursor:
        node = cursor.pop()
        if node.start_point[0] <= target <= node.end_point[0]:
            if node.type in binding_types:
                key = (node.end_point[0] - node.start_point[0], node.start_byte,
                       node.end_byte, node.type)
                if best_key is None or key < best_key:
                    best, best_key = node, key
            cursor.extend(node.children)
    return best


def bindings_at_line(root, lineno: int, binding_types):
    """対象行に交差し binding_types に属する全ノードを決定的順で返す（list）。

    binding_at_line（最小スパン単一ノード）と異なり、1行に複数の束縛が同居するケース
    （例: `int count = svc.getName(); obj.setValue(count);`）を全件返す。
    順序は (start_byte, end_byte, type) 昇順で安定（決定性）。
    name 行ゲート（method 系のみ name 行に絞る）は各 chaser ハンドラの責務。
    """
    target = lineno - 1
    out = []
    cursor = [root]
    while cursor:
        node = cursor.pop()
        if node.start_point[0] <= target <= node.end_point[0]:
            if node.type in binding_types:
                out.append(node)
            cursor.extend(node.children)
    out.sort(key=lambda n: (n.start_byte, n.end_byte, n.type))
    return out


class _ParseFailed(Exception):
    """tree-sitter parse() が例外を投げたことを表す内部シグナル。"""


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
    # コメント専用行（最小ノードが comment）は climb 前に短絡。
    # java=line_comment/block_comment、他=comment を endswith で一律カバー。
    if node is not None and node.type.endswith("comment"):
        return ("コメント", "low")
    while node is not None:
        cat = _CATEGORY_BY_LANG[language].get(node.type)
        if cat is not None:
            return (cat, "high")
        node = node.parent
    return ("その他", "high")


def parse_tree(language: str, source: str, cache: dict | None = None):
    """ソースを host_source で逆マスク後 parse し root_node を返す。

    `cache` を渡すと language をキーに root_node をメモ化する。ファイル単位で空 dict を
    使い回すことで複数回の parse_tree 呼出を 1 回に集約できる。`cache=None` は毎回 parse。

    parse() の例外は _ParseFailed に正規化して呼出側へ伝える。
    climb/辞書アクセス等のロジック例外は捕捉しない。
    """
    if cache is not None and language in cache:
        return cache[language]
    # _parser()（grammar 解決）と host_source()（逆マスク）は try の外に置く。
    # KeyError 等のロジック例外は握り潰さず即死させる。try は .parse() の1呼出のみ。
    parser = _parser(language)
    src_bytes = host_source(language, source).encode("utf-8")
    try:
        root = parser.parse(src_bytes).root_node
    except Exception as e:
        raise _ParseFailed(language) from e
    if cache is not None:
        cache[language] = root
    return root
