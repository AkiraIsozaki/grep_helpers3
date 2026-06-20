"""TypeScript / TSX の AST chaser を提供する（JS 規則＋enum/readonly field）。

JS 規則は javascript_chaser から再利用する。tsx は language 引数で grammar 変種を切り替える
（parse は呼出側が行い、本モジュールは root のみ受ける）。
"""
from grep_analyzer.classifiers.base import node_text
from grep_analyzer.classifiers.javascript_chaser import _BINDING as _JS_BINDING
from grep_analyzer.classifiers.javascript_chaser import handle_js_binding as _handle_js
from grep_analyzer.classifiers.ts_classifier import run_field_chase

_BINDING = _JS_BINDING | {"public_field_definition", "enum_declaration"}


def _handle_ts(node, consts, vars_, getters, setters):
    t = node.type
    if t == "public_field_definition":
        is_readonly = any(not c.is_named and node_text(c) == "readonly"
                          for c in node.children)
        name = node.child_by_field_name("name")
        if name is not None and name.type == "property_identifier":
            (consts if is_readonly else vars_).append(node_text(name))
    elif t == "enum_declaration":
        body = node.child_by_field_name("body")
        if body is not None:
            for ch in body.children:
                if ch.type == "property_identifier":
                    consts.append(node_text(ch))
                elif ch.type == "enum_assignment":
                    nm = ch.child_by_field_name("name")
                    if nm is not None:
                        consts.append(node_text(nm))
    else:
        _handle_js(node, consts, vars_, getters, setters)


def extract_tree(language, root, lineno):
    return run_field_chase(root, lineno, _BINDING, _handle_ts)
