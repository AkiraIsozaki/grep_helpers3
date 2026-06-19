"""pyahocorasick ラッパ。識別子語境界一致のみ採用し決定的に返す。

語境界判定（`_IDENT`）は **ASCII 英数字＋`_` のみ**を識別子文字とする意図的な設計である。
非ASCII（CJK・かな・アクセント付き Latin 等）は常に語境界として扱う。対象が SJIS/日本語
コーパスであり、日本語コメント・文字列に空白なく隣接する ASCII 識別子（関数名・変数名）を
取りこぼさず追跡することを優先するためである（例: `日本語var日本語` / `あvarい` から `var`
を採る。`test_automaton.py` で固定）。

トレードオフ: Unicode 識別子を持つ言語（例 `caféfoo`）では `é` が境界扱いとなり、識別子内の
ASCII 部分文字列 `foo` を偽陽性として拾い得る。これは上記の SJIS 近接マッチ優先のための
許容コストであり、欧文 Unicode 識別子は本ツールの主対象外である（H2・意図的トレードオフ）。
"""

import ahocorasick

_IDENT = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def build(symbols: list[str]) -> ahocorasick.Automaton | None:
    """非空シンボル集合から Automaton を構築する。空集合/全空文字は None を返す。"""
    nonempty_symbols = [s for s in symbols if s]
    if not nonempty_symbols:
        return None
    automaton_obj = ahocorasick.Automaton()
    for s in nonempty_symbols:
        automaton_obj.add_word(s, s)
    automaton_obj.make_automaton()
    return automaton_obj


def scan_line(automaton_obj: ahocorasick.Automaton | None, line: str) -> list[str]:
    """1 行から語境界一致シンボルを昇順ユニークで返す（決定的）。

    列挙は `set` で集約し最後に `sorted()` で正規化、採否は `end`/`len(symbol)` から
    算出する文字 index のみに依存し iter() の列挙順に非依存。これにより pyahocorasick の
    版差（iter 順序・同一終端多重）を構造的に吸収する（2.1.0→2.3.1 で出力 byte 不変を確認済）。
    """
    if automaton_obj is None:
        return []
    found = set()
    n = len(line)
    for end, symbol in automaton_obj.iter(line):
        start = end - len(symbol) + 1
        before = line[start - 1] if start > 0 else ""
        after = line[end + 1] if end + 1 < n else ""
        if before not in _IDENT and after not in _IDENT:
            found.add(symbol)
    return sorted(found)
