"""M2: diagnostics の detail に入るパスは sanitize_field を通し、パス内 TAB/CR が
列構造（`{category}\\t{message}`）を壊さないことを保証する。"""

from grep_analyzer.cli import main


def test_診断パスのタブは空白化され列構造を壊さない(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    inp = tmp_path / "input"
    inp.mkdir()
    # 存在しないファイルを TAB 入りパスで参照 → missing_source。
    (inp / "K.grep").write_bytes(b"a\tb.c:1:content\n")
    out = tmp_path / "o"
    assert main(["--input", str(inp), "--output", str(out),
                 "--source-root", str(src)]) == 0

    diag = (out / "diagnostics.txt").read_text("utf-8")
    detail = [ln for ln in diag.splitlines()
              if ln.startswith("missing_source\t") and not ln[15:].isdigit()]
    assert detail, diag                          # missing_source の detail 行が存在
    for ln in detail:
        assert ln.count("\t") == 1, ln           # パス内 TAB が混入していない
        assert "\r" not in ln
