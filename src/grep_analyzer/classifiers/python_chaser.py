"""Python の AST chaser を提供する（field-directed）。

ASTChaser プロトコルに準拠する。parse は呼出側が行う。
束縛導入ノードから name:/left: フィールドのみを抽出する（RHS/型は読まない）。
"""
import re

from grep_analyzer.classifiers.ast_base import node_text, run_field_chase

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


def _from_decorated(node, lineno, getters, setters):
    defn = node.child_by_field_name("definition")
    if defn is None or defn.type != "function_definition":
        return
    name_node = defn.child_by_field_name("name")
    if name_node is None:
        return
    # name 行ゲート（java_chaser と同契約）: decorated_definition は本体全行に
    # 交差するため、ゲートが無いと本体行のヒットすべてが getter/setter 名を放出し
    # 不動点追跡の terminal に偽シンボルが載る。
    if name_node.start_point[0] != lineno - 1:
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


def _handle_python(node, lineno, consts, vars_, getters, setters):
    if node.type == "decorated_definition":
        _from_decorated(node, lineno, getters, setters)
    else:
        _from_assignment(node, consts, vars_)


def extract_tree(language, root, lineno):
    """parse 済 root から Python 束縛を field-directed・multi-node 抽出する。"""
    return run_field_chase(
        root, lineno, _BINDING,
        lambda node, c, v, g, s: _handle_python(node, lineno, c, v, g, s))
