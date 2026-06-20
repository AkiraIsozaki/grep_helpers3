"""C-2: resume 完了 kw に対し finalize が呼ばれない（実スキップ）ことを spy で検証。"""

from pathlib import Path

from grep_analyzer import pipeline
from grep_analyzer.cli import main

_REPO = Path(__file__).resolve().parents[2]
_CASE = _REPO / "tests" / "golden" / "cases" / "cp932_indirect_multikw"


def _tsv_manifest(out_dir: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes()
            for p in sorted(out_dir.iterdir())
            if p.suffix == ".tsv" or p.name.endswith(".manifest.json")}


def test_一部完了からのresumeは無中断実行とTSVバイト同値(tmp_path):
    # 複数 keyword のうち一部だけ完了した状態から --resume すると、完了済はスキップ・
    # 未完了のみ再処理し、最終 TSV/manifest は無中断実行とバイト同値になる
    # （resume の本来シナリオ＝部分再開の正当性。diagnostics は resume_skipped 等で
    #  変動するため比較対象外）。
    args = ["--input", str(_CASE / "input"), "--source-root", str(_CASE / "src")]

    ref = tmp_path / "ref"
    assert main(args + ["--output", str(ref)]) == 0          # 無中断フル実行（基準）

    work = tmp_path / "work"
    assert main(args + ["--output", str(work)]) == 0         # 一旦フル実行（両 kw 完了）
    removed = list(work.glob("MAX_TIMEOUT*"))
    assert removed, "前提: MAX_TIMEOUT の出力が存在する"
    for p in removed:                                        # 1 kw を未完了状態に戻す
        p.unlink()

    assert main(args + ["--output", str(work), "--resume"]) == 0  # 完了 kw skip・未完了のみ再処理

    ref_snap, work_snap = _tsv_manifest(ref), _tsv_manifest(work)
    assert work_snap.keys() == ref_snap.keys()
    for name in ref_snap:
        assert work_snap[name] == ref_snap[name], f"partial-resume byte mismatch: {name}"


def _setup(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A{ static final int K1=1; }\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    (inp / "K1.grep").write_text("A.java:1:static final int K1=1;\n", "utf-8")
    return src, inp


def test_resume完了kwはfinalizeを呼ばない(tmp_path, monkeypatch):
    src, inp = _setup(tmp_path)
    out = tmp_path / "o"
    a = ["--input", str(inp), "--output", str(out), "--source-root", str(src)]
    assert main(a) == 0                                    # 1回目で完了

    calls: list[str] = []
    real_finalize = pipeline.output_writer.finalize

    def _spy(output_dir, keyword, rows, opts):
        calls.append(keyword)
        return real_finalize(output_dir, keyword, rows, opts)

    monkeypatch.setattr(pipeline.output_writer, "finalize", _spy)
    assert main(a + ["--resume"]) == 0                     # 2回目は resume
    assert calls == []                                     # 完了 kw は finalize 非呼出＝実スキップ


def test_未完了kwはresumeでも再処理される(tmp_path, monkeypatch):
    src, inp = _setup(tmp_path)
    out = tmp_path / "o"
    a = ["--input", str(inp), "--output", str(out), "--source-root", str(src)]
    assert main(a) == 0
    (out / "K1.manifest.json").unlink()                    # 完了痕跡を消す

    calls: list[str] = []
    real_finalize = pipeline.output_writer.finalize
    monkeypatch.setattr(pipeline.output_writer, "finalize",
                        lambda *x, **kw: (calls.append(x[1]), real_finalize(*x, **kw))[1])
    assert main(a + ["--resume"]) == 0
    assert calls == ["K1"]                                 # manifest 無し→再処理される
