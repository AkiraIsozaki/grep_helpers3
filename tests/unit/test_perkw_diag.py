from grep_analyzer.pipeline import run
from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.walk import DEFAULT_EXCLUDE


def _setup(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "a.c").write_bytes("int foo; int bar;\n".encode("cp932"))
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "foo.grep").write_bytes(f"{src/'a.c'}:1:int foo; int bar;\n".encode())
    return src, inp


def test_perkw_diagをoffにしてもper_keywordのTSVは完全一致する(tmp_path):
    src, inp = _setup(tmp_path)
    common = dict(jobs=1, exclude=list(DEFAULT_EXCLUDE), use_ripgrep=True)
    run(inp, tmp_path / "on", src, EngineOptions(perkw_diag=True, **common))
    run(inp, tmp_path / "off", src, EngineOptions(perkw_diag=False, **common))
    on = sorted(p.name for p in (tmp_path / "on").glob("*.tsv"))
    off = sorted(p.name for p in (tmp_path / "off").glob("*.tsv"))
    assert on == off
    for name in on:
        assert (tmp_path / "on" / name).read_bytes() == (tmp_path / "off" / name).read_bytes()
