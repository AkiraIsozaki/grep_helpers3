"""M2: diagnostics の detail に入るパスは sanitize_field を通し、パス内 TAB/CR が
列構造（`{category}\\t{message}`）を壊さないことを保証する。"""

import dataclasses

from grep_analyzer.cli import main
from grep_analyzer.pipeline import _default_opts, run


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


def test_indirect経路のdecode_replacedパスもサニタイズされる(tmp_path):
    # indirect/absorb 経路（_ingest）の decode_replaced も sanitize_field を通す（M2 完全化）。
    src = tmp_path / "src"
    src.mkdir()
    # seed: chase を生む KCODE
    (src / "main.java").write_text(
        "class M { static final int KCODE=1; int r=KCODE; }\n", "utf-8")
    # TAB 入り名の replaced=True ファイル（KCODE を含まないが全件走査で scan される）
    (src / "a\tb.java").write_bytes(
        "class Zzz {}\n".encode("utf-8") + b"// \x80\x81\xfd\xfe\xff\n")
    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "KCODE.grep").write_text(
        "main.java:1:class M { static final int KCODE=1; int r=KCODE; }\n", "utf-8")

    out = tmp_path / "o"
    # use_ripgrep=False ＝ TAB ファイルを必ず走査対象に残す（indirect で decode_replaced 発火）
    opts = dataclasses.replace(_default_opts(), jobs=1, use_ripgrep=False)
    assert run(input_dir=inp, output_dir=out, source_root=src, opts=opts) == 0

    diag = (out / "diagnostics.txt").read_text("utf-8")
    dr = [ln for ln in diag.splitlines()
          if ln.startswith("decode_replaced\t") and "b.java" in ln]
    assert dr, diag                              # indirect の decode_replaced 行が存在
    for ln in dr:
        assert ln.count("\t") == 1, ln           # パス内 TAB が混入していない
