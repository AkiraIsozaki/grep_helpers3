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

import string

import ahocorasick

_IDENT = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")

# ASCII A-Z のみを小文字へ畳む（長さ保存＝index 算術が生きる。str.lower() は
# 一部 Unicode で長さが変わり得るため使わない）。
_ASCII_FOLD = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)

# 大小無別で照合する言語（PL/SQL 識別子は大文字小文字を区別しない）。
# 抽出側（ORACLE_DECL_ASSIGN_RE 等）は IGNORECASE なのに照合側が区別すると、
# 宣言 `V_CNT NUMBER := 0` から抽出した記号が参照行 `v_cnt := 1` に不一致となり
# indirect 行が丸ごと欠落する（照合の非対称）。
CASE_INSENSITIVE_LANGS = frozenset({"sql"})


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


def build_ci(symbols: list[str]) -> ahocorasick.Automaton | None:
    """ASCII 畳み込みキーで Automaton を構築する（値は原綴りの決定的 tuple）。

    大小違いのみの複数原綴りは同一キーへ集約し sorted tuple で保持する
    （scan 側はヒット 1 箇所から全原綴りを報告する）。
    """
    folded: dict[str, set[str]] = {}
    for s in symbols:
        if s:
            folded.setdefault(s.translate(_ASCII_FOLD), set()).add(s)
    if not folded:
        return None
    automaton_obj = ahocorasick.Automaton()
    for key, originals in folded.items():
        automaton_obj.add_word(key, tuple(sorted(originals)))
    automaton_obj.make_automaton()
    return automaton_obj


def build_pair(symbols: list[str]):
    """(case-sensitive, ASCII 畳み込み) の Automaton 対を構築する。

    scan_line_for_language が言語に応じて使い分ける。どちらも空なら (None, None)。
    """
    return build(symbols), build_ci(symbols)


def scan_line_for_language(pair, line: str, language: str) -> list[str]:
    """言語の識別子規約に従い 1 行を照合する（CASE_INSENSITIVE_LANGS は大小無別）。"""
    cs_automaton, ci_automaton = pair
    if language in CASE_INSENSITIVE_LANGS:
        return _scan_line_ci(ci_automaton, line)
    return scan_line(cs_automaton, line)


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


def _scan_line_ci(ci_automaton, line: str) -> list[str]:
    """ASCII 畳み込み行を照合し原綴り集合を昇順ユニークで返す（決定的）。

    畳み込みは長さ保存なので語境界 index は原行と一致する。境界文字集合 _IDENT は
    大小両方を含むため、畳み込み行での境界判定は原行と同値である。
    """
    if ci_automaton is None:
        return []
    folded_line = line.translate(_ASCII_FOLD)
    found = set()
    n = len(folded_line)
    for end, originals in ci_automaton.iter(folded_line):
        start = end - len(originals[0]) + 1
        before = folded_line[start - 1] if start > 0 else ""
        after = folded_line[end + 1] if end + 1 < n else ""
        if before not in _IDENT and after not in _IDENT:
            found.update(originals)
    return sorted(found)
