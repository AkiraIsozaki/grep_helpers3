"""pytest 共通設定。src レイアウトを import 可能にする。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "requires_ripgrep: 実 ripgrep を要する（無ければ skip）")


@pytest.fixture(autouse=True)
def _reset_rg_cache():
    from grep_analyzer import ripgrep
    ripgrep._RG_RESOLVED = False
    ripgrep._RG_CACHE = None
    yield


def pytest_collection_modifyitems(config, items):
    import re
    from grep_analyzer import ripgrep
    rg = ripgrep.available()
    markexpr = config.getoption("markexpr") or ""        # -m の式（"-m" でなく markexpr）
    # "perf" がトークンとして式に現れるか（"not perf" 等の部分文字列誤判定回避）。
    perf_selected = bool(re.search(r"\bperf\b", markexpr))
    skip_rg = pytest.mark.skip(reason="ripgrep 不在のため skip（任意機能）")
    skip_perf = pytest.mark.skip(reason="perf は非ゲート（既定除外）")
    applied_rg_skip = False
    for item in items:
        if "requires_ripgrep" in item.keywords and not rg:
            item.add_marker(skip_rg)
            applied_rg_skip = True
        if "perf" in item.keywords and not perf_selected:
            item.add_marker(skip_perf)
    # C4: rg が解決可能なのに rg skip を付けたら gate バグ（理由文字列に依存しない検査）。
    assert not (rg and applied_rg_skip), \
        "rg 解決可能なのに requires_ripgrep を skip した（C4 gate）"
