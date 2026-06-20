"""言語別リテラル / コメントのマスク用 regex を定義する。

リテラル文字列・コメントを同字数空白に置換する言語別パターン集。
マッチ全体を空白に潰すため、後段の抽出は行番号・桁を保ったまま行える。

注: java/c は AST 経路のため MASK_SPECS の対象外である。
    proc は proc_preprocess.py が MASK_PATTERNS["proc"] に直接依存するため残している。
"""

import re

MASK_SPECS: dict[str, list[str]] = {
    "proc": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "sql": [r"'(?:''|[^'])*'", r"--[^\n]*", r"/\*.*?\*/"],
    "shell": [r'"(?:\\.|[^"\\])*"', r"'[^']*'", r"#[^\n]*"],
    # q/qq の代替デリミタを保守的にマスクする（M）。括弧3種＋bang。sigil 変数 $q/@q を
    # 誤マスクしないよう (?<![$@%]) を付す。ネスト括弧・heredoc・任意デリミタ(s///等)は
    # 依然 既知境界（perl_chaser docstring 参照）。
    "perl": [r"'[^']*'", r'"(?:\\.|[^"\\])*"',
             r"(?<![$@%])\bqq?\([^)]*\)", r"(?<![$@%])\bqq?\{[^}]*\}",
             r"(?<![$@%])\bqq?\[[^\]]*\]", r"(?<![$@%])\bqq?<[^>]*>",
             r"(?<![$@%])\bqq?![^!]*!",
             r"(?<![$@%])#[^\n]*"],
    "groovy": [r"'(?:\\.|[^'\\])*'", r'"(?:\\.|[^"\\])*"', r"//[^\n]*", r"/\*.*?\*/"],
}

MASK_PATTERNS: dict[str, re.Pattern[str]] = {
    lang: re.compile("|".join(p), re.DOTALL) for lang, p in MASK_SPECS.items()
}


def blank_spans(pattern: re.Pattern[str], text: str) -> str:
    """pattern のマッチ全体を同字数空白へ置換する（行番号・桁を保つ）。"""
    return pattern.sub(lambda m: " " * len(m.group(0)), text)


def mask_literals(language: str, line: str) -> str:
    """language のリテラル/コメントを同字数空白へ置換する。未登録言語は素通しする。"""
    pat = MASK_PATTERNS.get(language)
    return line if pat is None else blank_spans(pat, line)
