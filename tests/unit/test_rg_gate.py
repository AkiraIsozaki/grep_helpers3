"""C4: rg が解決可能なら requires_ripgrep テストは skip されず実走する。"""
import pytest

from grep_analyzer import ripgrep


@pytest.mark.requires_ripgrep
def test_rg解決可能なら本テストは実走する():
    # rg 不在環境では conftest が skip する。rg 配置環境では実走し、
    # available() と _resolve_rg() が整合することを確認する（gate の健全性）。
    assert ripgrep.available() is True
    assert ripgrep._resolve_rg() is not None
