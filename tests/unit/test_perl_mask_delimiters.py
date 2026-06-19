"""Perl の q/qq が () 以外のデリミタでもマスクされ偽抽出を防ぐことを検証する（M）。

旧実装は `q(...)` / `qq(...)` の丸括弧デリミタのみマスクし、`q{...}` `q[...]` `q<...>`
`q!...!` 内の sigil 付き擬似代入を追跡シンボルとして誤抽出していた。代表的な代替
デリミタ（括弧3種＋bang）を保守的にマスクする。ネストや heredoc/任意デリミタは
依然 既知境界（docstring 参照）。
"""

import pytest

from grep_analyzer.classifiers.perl_chaser import extract


def _symbols(line: str):
    cs = extract("perl", line)
    return set(cs.vars) | set(cs.constants)


@pytest.mark.parametrize("line", [
    "print q{x $foo = bar};",
    "print q[x $foo = bar];",
    "print q<x $foo = bar>;",
    "print q!x $foo = bar!;",
    "print qq{x $foo = bar};",
])
def test_代替デリミタのq内のsigil代入は抽出されない(line):
    assert "foo" not in _symbols(line)


def test_素の代入は従来どおり抽出される():
    # リグレッションガード: マスク対象外の実コードの代入は引き続き拾う。
    assert "foo" in _symbols("my $foo = 1;")
