"""JavaScript の AST chaser を提供する（field-directed）。

`handle_js_binding` / `_BINDING` は typescript_chaser と共有する。
"""
from grep_analyzer.classifiers.base import node_text
from grep_analyzer.classifiers.ts_classifier import run_field_chase

_BINDING = {"lexical_declaration", "variable_declaration",
            "assignment_expression", "augmented_assignment_expression",
            "field_definition", "method_definition"}


def _names_from_pattern(node, out):
    t = node.type
    if t in ("identifier", "shorthand_property_identifier_pattern"):
        out.append(node_text(node))
    elif t == "object_pattern":
        for ch in node.children:
            if ch.type == "shorthand_property_identifier_pattern":
                out.append(node_text(ch))
            elif ch.type == "pair_pattern":
                val = ch.child_by_field_name("value")
                if val is not None:
                    _names_from_pattern(val, out)        # key は読まない
            elif ch.type == "object_assignment_pattern":
                left = ch.child_by_field_name("left")
                if left is not None:
                    _names_from_pattern(left, out)        # デフォルト値 right は読まない
            elif ch.type == "rest_pattern":
                for c in ch.children:
                    if c.type == "identifier":
                        out.append(node_text(c))
    elif t == "assignment_pattern":
        left = node.child_by_field_name("left")
        if left is not None:
            _names_from_pattern(left, out)
    elif t == "array_pattern":
        for ch in node.children:
            if ch.type == "identifier":
                out.append(node_text(ch))
            elif ch.type in ("object_pattern", "array_pattern"):
                _names_from_pattern(ch, out)
            elif ch.type == "assignment_pattern":
                left = ch.child_by_field_name("left")
                if left is not None:
                    _names_from_pattern(left, out)
            elif ch.type == "rest_pattern":
                for c in ch.children:
                    if c.type == "identifier":
                        out.append(node_text(c))


def _declarators(decl, is_const, consts, vars_):
    target = consts if is_const else vars_
    for ch in decl.children:
        if ch.type != "variable_declarator":
            continue
        name = ch.child_by_field_name("name")
        if name is not None:
            _names_from_pattern(name, target)


def handle_js_binding(node, consts, vars_, getters, setters):
    t = node.type
    if t == "lexical_declaration":
        is_const = any(not c.is_named and node_text(c) == "const"
                       for c in node.children)
        _declarators(node, is_const, consts, vars_)
    elif t == "variable_declaration":
        _declarators(node, False, consts, vars_)
    elif t in ("assignment_expression", "augmented_assignment_expression"):
        left = node.child_by_field_name("left")
        if left is not None and left.type == "identifier":
            vars_.append(node_text(left))
    elif t == "field_definition":
        prop = node.child_by_field_name("property")
        if prop is not None and prop.type in ("property_identifier", "private_property_identifier"):
            vars_.append(node_text(prop))
    elif t == "method_definition":
        kind = None
        for c in node.children:
            if not c.is_named and node_text(c) in ("get", "set"):
                kind = node_text(c)
                break
        name = node.child_by_field_name("name")
        if kind and name is not None and name.type == "property_identifier":
            (getters if kind == "get" else setters).append(node_text(name))


def extract_tree(language, root, lineno):
    return run_field_chase(root, lineno, _BINDING, handle_js_binding)
