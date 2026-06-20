"""巨大/parse 失敗の seed ファイルで initialize_state がクラッシュしないこと（#K リグレッション）。"""

from pathlib import Path

from grep_analyzer.classifiers import ast_base
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.fixedpoint._seed import initialize_state
from grep_analyzer.model import Hit


def _seed_hit(file):
    return Hit(keyword="K", language="java", file=file, lineno=1, ref_kind="direct",
               category="", category_sub="", usage_summary="", via_symbol="",
               chain="", snippet="", encoding="utf-8", confidence="high")


def test_parse上限超のseedファイルでクラッシュせず空抽出に降格(tmp_path, monkeypatch):
    monkeypatch.setattr(ast_base, "_MAX_PARSE_BYTES", 50)
    src = tmp_path / "Big.java"
    src.write_text("class A { int x = 1; }\n" + "// pad\n" * 20, "utf-8")  # >50 bytes
    opts = EngineOptions()
    diag = Diagnostics()
    # _ParseFailed が初期化を倒さないこと（seed の AST 抽出は空へ降格）。
    state = initialize_state([_seed_hit("Big.java")], tmp_path, opts, diag)
    assert state is not None
