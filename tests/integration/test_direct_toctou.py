import os
from pathlib import Path
from grep_analyzer.pipeline import _default_opts, run


def test_direct読込のTOCTOUはmissing_sourceに降格しrunを落とさない(tmp_path, monkeypatch):
    src = tmp_path / "src"; src.mkdir()
    f = src / "a.c"; f.write_text("int x;\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "K.grep").write_text("a.c:1:int x;\n", "utf-8")
    out = tmp_path / "o"
    # is_file は通るが read で OSError（walk 後の TOCTOU を模擬）。read 方式に依らず
    # 落とすため、open を a.c に対してだけ失敗させる。
    real_open = open
    def boom(file, *a, **k):
        if str(file).endswith("/a.c"):
            raise OSError("vanished")
        return real_open(file, *a, **k)
    monkeypatch.setattr("builtins.open", boom)
    rc = run(input_dir=inp, output_dir=out, source_root=src, opts=_default_opts())
    assert rc == 0
    diag = (out / "diagnostics.txt").read_text("utf-8")
    assert "missing_source" in diag and "a.c" in diag
