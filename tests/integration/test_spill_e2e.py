"""C-1: spill 経路を出力非空のまま通し、spill 有/無のバイト同値を凍結する。"""

import dataclasses

from grep_analyzer.pipeline import _default_opts, run


def _setup(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    # 定数→変数→使用の多ホップ（別行・min_specificity>=2 を満たす長い識別子）で
    # indirect:constant / indirect:var を複数生む構成＝来歴エッジ>0（spill 経由を要する）。
    (src / "C.java").write_text(
        "class C {\n"
        "  static final int THRESHOLD = 1;\n"
        "  int limit = THRESHOLD;\n"
        "  int total = limit;\n"
        "}\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    (inp / "THRESHOLD.grep").write_text(
        "C.java:2:  static final int THRESHOLD = 1;\n", "utf-8")
    return src, inp


def test_spill経由でも出力は非空かつspillなしとバイト同値(tmp_path):
    src, inp = _setup(tmp_path)
    base = dataclasses.replace(_default_opts(), spill_dir=tmp_path / "spill")
    (tmp_path / "spill").mkdir()

    out_no = tmp_path / "no"
    assert run(input_dir=inp, output_dir=out_no, source_root=src, opts=base) == 0
    bytes_no = (out_no / "THRESHOLD.tsv").read_bytes()

    out_sp = tmp_path / "sp"
    spilled = dataclasses.replace(base, force_spill=1)        # 1 エッジ目から spill
    assert run(input_dir=inp, output_dir=out_sp, source_root=src, opts=spilled) == 0
    bytes_sp = (out_sp / "THRESHOLD.tsv").read_bytes()

    # 出力は非空（indirect 行が存在）かつ spill 有無でバイト同値
    assert b"indirect" in bytes_no
    assert bytes_sp == bytes_no


def test_graph_spilled診断が件数とhopを記録(tmp_path):
    """memory_limit_mb=0 で spill を誘発し、graph_spilled 診断が件数と hop= フォーマットで
    記録されることを固定する（C2）。

    memory_limit_mb=0 は item_budget=0 に換算され、シンボル 1 件でも budget.exceeded が
    True になるため必ず hop=1 で graph_spilled が発火する（force_spill は EdgeStore の
    _force_spill_threshold を設定するが _budget_control.maybe_spill の budget チェックとは
    別経路のため診断を出さない）。

    diagnostics.txt の summary に graph_spilled の件数が、
    detail に "hop=" を含む行が存在することを assert する。
    """
    src, inp = _setup(tmp_path)
    out = tmp_path / "out"
    opts = dataclasses.replace(_default_opts(), memory_limit_mb=0)  # 即時 budget 超過 → spill
    assert run(input_dir=inp, output_dir=out, source_root=src, opts=opts) == 0

    diag_text = (out / "diagnostics.txt").read_text("utf-8")

    # summary に graph_spilled が記録されていること（件数 >= 1）。
    summary: dict[str, int] = {}
    in_summary = False
    for ln in diag_text.splitlines():
        if ln == "# summary":
            in_summary = True
            continue
        if ln == "# detail":
            break
        if in_summary and ln:
            cat, _, val = ln.partition("\t")
            summary[cat] = int(val)

    assert "graph_spilled" in summary, \
        f"graph_spilled が diagnostics summary に無い（summary={summary}）"
    assert summary["graph_spilled"] >= 1, \
        f"graph_spilled の件数が 0（summary={summary}）"

    # detail に "hop=" を含む行が存在すること（フォーマット固定）。
    detail_lines: list[str] = []
    in_detail = False
    for ln in diag_text.splitlines():
        if ln == "# detail":
            in_detail = True
            continue
        if in_detail and ln.startswith("graph_spilled\t"):
            detail_lines.append(ln)

    assert detail_lines, "graph_spilled の detail 行が無い"
    assert any("hop=" in ln for ln in detail_lines), \
        f"graph_spilled detail に 'hop=' が含まれない（detail={detail_lines}）"
