"""tree-sitter の parse／走査基盤。AST chaser と分類器が共有する。

tree-sitter wheel 欠落でも regex トラックを起動可能にするため遅延 import する。
AST 経路（java/c/proc/jsp/angular/angular_inline/python/javascript/typescript/tsx）に
初めて到達したときだけ wheel を import する。欠落時は ModuleNotFoundError がその呼出で
顕在化し、呼出側 regex 経路は影響を受けない。
"""

from grep_analyzer.embed_preprocess import host_grammar, host_source
from grep_analyzer.model import dedup_symbols

_LANGS: dict | None = None


def _ensure_langs() -> dict:
    """tree-sitter grammar を初回アクセス時に遅延構築する。"""
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


# Parser は grammar ごとに 1 度だけ生成して再利用する（parse は毎回新 Tree を返すので再利用安全）。
# jobs>1 はプロセス並列なので各プロセスが独立した dict を持ち、スレッド共有は無い。
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


def node_text(node) -> str:
    """tree-sitter ノードのバイト列を UTF-8 文字列へ復号する（不正バイトは置換）。"""
    return node.text.decode("utf-8", "replace")


def _span_key(node):
    """node_at_line/binding_at_line が使う全順序キー（走査順に依存しない一意選択用）。"""
    return (node.end_point[0] - node.start_point[0], node.start_byte,
            node.end_byte, node.type)


def _nodes_covering(root, target: int):
    """target 行（0 始まり）を内包するノードを走査順に yield する。

    親が target を内包するときだけ子へ降りる（最小ノード探索の枝刈り）。
    走査順は決定的なので、同一キーのノードは最初に出会ったものが優先される。
    """
    cursor = [root]
    while cursor:
        node = cursor.pop()
        if node.start_point[0] <= target <= node.end_point[0]:
            yield node
            cursor.extend(node.children)


def node_at_line(root, lineno: int):
    """対象行（lineno は 1 始まり）を内包する最小ノードを決定的に返す。

    `_span_key`（行スパン, start_byte, end_byte, 型）の最小で一意選択する。
    classify_ts と snippet/_ts.py が共有する。
    """
    return min(_nodes_covering(root, lineno - 1), key=_span_key, default=None)


def binding_at_line(root, lineno: int, binding_types):
    """対象行を内包し binding_types に属する最小スパンノードを決定的に返す。

    node_at_line と同じ全順序キーで一意選択。「最左最小葉から climb」では届かない
    束縛（例: `class C { get x() {} }`）を直接拾うために使う。該当なしは None。
    """
    covering = (n for n in _nodes_covering(root, lineno - 1) if n.type in binding_types)
    return min(covering, key=_span_key, default=None)


def bindings_at_line(root, lineno: int, binding_types):
    """対象行に交差し binding_types に属する全ノードを決定的順で返す（list）。

    binding_at_line（最小スパン単一ノード）と異なり、1行に複数の束縛が同居するケース
    （例: `int count = svc.getName(); obj.setValue(count);`）を全件返す。
    順序は (start_byte, end_byte, type) 昇順で安定（決定性）。
    name 行ゲート（method 系のみ name 行に絞る）は各 chaser ハンドラの責務とする。
    """
    out = [n for n in _nodes_covering(root, lineno - 1) if n.type in binding_types]
    out.sort(key=lambda n: (n.start_byte, n.end_byte, n.type))
    return out


def run_field_chase(root, lineno, binding_types, handler):
    """対象行の束縛ノードを handler に渡し、集めた4分類を dedup_symbols で正規化して返す。

    各 AST chaser の extract_tree が共有する骨格。handler は
    `(node, consts, vars_, getters, setters)` を受け取り、該当リストへ name を append する。
    const/var 抑止・出現順 uniq は dedup_symbols に委譲する（全 chaser 共通）。
    """
    consts, vars_, getters, setters = [], [], [], []
    for node in bindings_at_line(root, lineno, binding_types):
        handler(node, consts, vars_, getters, setters)
    return dedup_symbols(consts, vars_, getters, setters)


# これを超える host_source（UTF-8 bytes）は AST parse を諦め非 AST 経路へ降格する（#K）。
# 通常 --max-file-bytes(既定5MB) で巨大ファイルは walk 除外されるが、上限を引き上げた運用で
# 巨大 minified/生成ファイルが流入すると 1 ファイルで worker が OOM し得る。決定的に
# ("その他","low")＋1行 snippet へ落とす（再 parse もしない）。
_MAX_PARSE_BYTES = 12 * 1024 * 1024


class _ParseFailed(Exception):
    """tree-sitter parse() が例外を投げた／巨大すぎて parse を諦めた内部シグナルである。"""


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
    # KeyError 等のロジック例外は握り潰さず即死させる。try は .parse() の1呼出のみに絞る。
    parser = _parser(language)
    src_bytes = host_source(language, source).encode("utf-8")
    if len(src_bytes) > _MAX_PARSE_BYTES:
        raise _ParseFailed(language)        # OOM 回避＝非 AST 経路へ決定的降格（#K）
    try:
        root = parser.parse(src_bytes).root_node
    except Exception as e:
        raise _ParseFailed(language) from e
    if cache is not None:
        cache[language] = root
    return root
