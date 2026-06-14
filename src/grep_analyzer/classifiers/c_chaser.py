"""C / Pro*C 用の AST Chaser であり、field-directed・multi-node で抽出する。

C と Pro*C は同じ抽出規則を共有する（Pro*C は C のスーパーセット）。
`ASTChaser` プロトコル準拠の `extract_tree` を公開し、
`_AST_CHASERS["c"]` / `_AST_CHASERS["proc"]` 経由で呼び出す。
Pro*C の EXEC SQL 区間は mask_exec_sql で空白化済みである。
"""

from grep_analyzer.classifiers.ts_classifier import bindings_at_line
from grep_analyzer.model import dedup_symbols

_AST_BINDING = {"declaration", "field_declaration", "preproc_def",
                "preproc_function_def", "assignment_expression"}


def _declarator_name(node):
    """init/pointer/array declarator を再帰的に剥がして末尾 identifier を返す。"""
    t = node.type
    if t in ("identifier", "field_identifier"):
        return node.text.decode("utf-8", "replace")
    if t in ("init_declarator", "pointer_declarator", "array_declarator"):
        d = node.child_by_field_name("declarator")
        return _declarator_name(d) if d is not None else None
    return None     # function_declarator（関数名・関数ポインタ等）は対象外とする


def _decl_names(node, out):
    for ch in node.children:
        if ch.type in ("init_declarator", "pointer_declarator", "array_declarator",
                       "identifier", "field_identifier"):
            nm = _declarator_name(ch)
            if nm is not None:
                out.append(nm)


def _is_const(node) -> bool:
    # tree-sitter-c の type_qualifier は1トークン1ノードである（const/volatile/...）
    return any(ch.type == "type_qualifier" and ch.text.decode("utf-8", "replace") == "const"
               for ch in node.children)


def _handle_c(node, consts, vars_):
    t = node.type
    if t in ("preproc_def", "preproc_function_def"):
        nm = node.child_by_field_name("name")
        if nm is not None:
            consts.append(nm.text.decode("utf-8", "replace"))
    elif t in ("declaration", "field_declaration"):
        _decl_names(node, consts if _is_const(node) else vars_)
    elif t == "assignment_expression":
        left = node.child_by_field_name("left")
        if left is not None and left.type == "identifier":
            vars_.append(left.text.decode("utf-8", "replace"))


def extract_tree(language, root, lineno):
    """parse 済 root から C/Pro*C 束縛を field-directed・multi-node 抽出する。"""
    consts, vars_ = [], []
    for node in bindings_at_line(root, lineno, _AST_BINDING):
        _handle_c(node, consts, vars_)
    # const/var 抑止・出現順 uniq は dedup_symbols に委譲する（全 chaser 共通）。
    return dedup_symbols(consts, vars_, (), ())
