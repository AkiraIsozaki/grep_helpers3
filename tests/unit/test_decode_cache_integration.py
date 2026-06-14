from pathlib import Path

from grep_analyzer.pipeline import run
from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.walk import DEFAULT_EXCLUDE


def _setup(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "a.c").write_bytes("int foo;\nint bar;\n".encode("cp932"))
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "foo.grep").write_bytes(f"{src/'a.c'}:1:int foo;\n".encode())
    return src, inp


def test_decode_cache有効時もjobs1とjobs2でTSVが完全一致する(tmp_path):
    src, inp = _setup(tmp_path)
    out1 = tmp_path / "o1"; out2 = tmp_path / "o2"
    run(inp, out1, src, EngineOptions(jobs=1, exclude=list(DEFAULT_EXCLUDE),
                                      decode_cache_dir=tmp_path / "dc1"))
    run(inp, out2, src, EngineOptions(jobs=2, exclude=list(DEFAULT_EXCLUDE),
                                      decode_cache_dir=tmp_path / "dc2"))
    a = sorted(p.name for p in out1.glob("*.tsv"))
    b = sorted(p.name for p in out2.glob("*.tsv"))
    assert a == b
    for name in a:
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()
