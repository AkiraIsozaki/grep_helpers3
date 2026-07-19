"""巨大ファイルの parse 断念判定をファイル単位 cache に記録する仕様。

判定のたびに全文 UTF-8 encode をやり直すと、同一巨大ファイルの全ヒット×
（classify＋snippet）で O(hits×size) になる。cache 付き呼出は 2 度目以降
encode を省いて即 _ParseFailed に到達すること。
"""
import pytest

from grep_analyzer.classifiers import ast_base


def test_サイズ超過の断念はcacheに記録され2度目のencodeを省く(monkeypatch):
    calls = {"n": 0}
    real_host_source = ast_base.host_source

    def counting_host_source(language, source):
        calls["n"] += 1
        return real_host_source(language, source)

    monkeypatch.setattr(ast_base, "host_source", counting_host_source)
    monkeypatch.setattr(ast_base, "_MAX_PARSE_BYTES", 10)
    cache: dict = {}
    with pytest.raises(ast_base._ParseFailed):
        ast_base.parse_tree("python", "x = 1  # 10バイト超のソース", cache=cache)
    with pytest.raises(ast_base._ParseFailed):
        ast_base.parse_tree("python", "x = 1  # 10バイト超のソース", cache=cache)
    assert calls["n"] == 1
