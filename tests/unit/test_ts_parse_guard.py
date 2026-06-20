"""A4: tree-sitter parse() 例外時に全体を落とさず降格する（snippet と対称）。"""
from grep_analyzer.classifiers import ast_base
from grep_analyzer.classifiers.ts_classifier import classify_ts
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.model import ChaseSymbols


class _BoomParser:
    def parse(self, *a, **k):
        raise RuntimeError("boom")


def test_parse例外は分類を降格しクラッシュしない(monkeypatch):
    # _parser が必ず例外を投げる Parser を返すよう差し替え
    monkeypatch.setattr(ast_base, "_parser", lambda lang: _BoomParser())
    cat, conf = classify_ts("java", "class C {}\n", 1)
    assert (cat, conf) == ("その他", "low")


def test_parse例外時にdiagへts_parse_failedを記録(monkeypatch):
    monkeypatch.setattr(ast_base, "_parser", lambda lang: _BoomParser())
    diag = Diagnostics()
    classify_ts("java", "class C {}\n", 1, diag=diag)
    assert "ts_parse_failed" in diag.render(detail_limit=0)


def test_parse例外時にchaseは空ChaseSymbolsを返す(monkeypatch):
    from grep_analyzer.chase import extract_chase_symbols_tree
    monkeypatch.setattr(ast_base, "_parser", lambda lang: _BoomParser())
    result = extract_chase_symbols_tree("java", "int K = 1;\n", 1)
    assert result == ChaseSymbols()
