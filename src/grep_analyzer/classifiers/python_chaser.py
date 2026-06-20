"""Python の AST chaser を提供する（field-directed）。

ASTChaser プロトコルに準拠する。parse は呼出側が行う。
束縛導入ノードから name:/left: フィールドのみを抽出する（RHS/型は読まない）。
"""
import re

from grep_analyzer.classifiers.ts_classifier import bindings_at_line
from grep_analyzer.classifiers.base import node_text
from grep_analyzer.model import dedup_symbols

_BINDING = {"assignment", "augmented_assignment", "decorated_definition"}
_CONST_RE = re.compile(r"^[A-Z_][A-Z0-9_]+$")


def _names_from_target(node, consts, vars_):
    t = node.type
    if t == "identifier":
        name = node_text(node)
        (consts if _CONST_RE.match(name) else vars_).append(name)
    elif t in ("pattern_list", "tuple_pattern", "list_pattern"):
        for ch in node.children:
            if ch.is_named:
                _names_from_target(ch, consts, vars_)
    elif t == "list_splat_pattern":
        for ch in node.children:
            if ch.type == "identifier":
                vars_.append(node_text(ch))
    # attribute(self.x) / subscript(d[k]) は束縛でないため抽出しない


def _from_assignment(node, consts, vars_):
    left = node.child_by_field_name("left")
    if left is not None:
        _names_from_target(left, consts, vars_)
    right = node.child_by_field_name("right")
    while right is not None and right.type == "assignment":  # 連鎖代入 a = b = 1
        l2 = right.child_by_field_name("left")
        if l2 is not None:
            _names_from_target(l2, consts, vars_)
        right = right.child_by_field_name("right")


def _from_decorated(node, getters, setters):
    defn = node.child_by_field_name("definition")
    if defn is None or defn.type != "function_definition":
        return
    name_node = defn.child_by_field_name("name")
    if name_node is None:
        return
    name = node_text(name_node)
    for ch in node.children:
        if ch.type != "decorator":
            continue
        expr = next((c for c in ch.children if c.is_named), None)
        if expr is None:
            continue
        if expr.type == "identifier" and node_text(expr) == "property":
            getters.append(name)
            return
        if expr.type == "attribute":
            attr = expr.child_by_field_name("attribute")
            if attr is not None and node_text(attr) == "setter":
                setters.append(name)
                return


def extract_tree(language, root, lineno):
    consts, vars_, getters, setters = [], [], [], []
    for node in bindings_at_line(root, lineno, _BINDING):
        if node.type == "decorated_definition":
            _from_decorated(node, getters, setters)
        else:
            _from_assignment(node, consts, vars_)
    return dedup_symbols(consts, vars_, getters, setters)
