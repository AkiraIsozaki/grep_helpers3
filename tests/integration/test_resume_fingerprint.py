"""H1: resume は入力 .grep / 行に影響するオプションの指紋を持ち、変化時は完了扱いせず
再処理する（黙って stale 出力を温存しない）。"""

from pathlib import Path

from grep_analyzer import pipeline
from grep_analyzer.cli import main


def _setup(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "A.java").write_text(
        "class A{ static final int K1=1; static final int K2=2; }\n", "utf-8")
    inp = tmp_path / "input"
    inp.mkdir()
    g = inp / "K1.grep"
    g.write_text("A.java:1:static final int K1=1;\n", "utf-8")
    return src, inp, g


def _spy_finalize(monkeypatch):
    calls: list[str] = []
    real = pipeline.output_writer.finalize
    monkeypatch.setattr(pipeline.output_writer, "finalize",
                        lambda *x, **kw: (calls.append(x[1]), real(*x, **kw))[1])
    return calls


def test_grep編集後のresumeは完了kwを再処理する(tmp_path, monkeypatch):
    src, inp, g = _setup(tmp_path)
    out = tmp_path / "o"
    a = ["--input", str(inp), "--output", str(out), "--source-root", str(src)]
    assert main(a) == 0                                    # 1 回目で完了

    g.write_text("A.java:1:static final int K2=2;\n", "utf-8")  # 入力 .grep を編集
    calls = _spy_finalize(monkeypatch)
    assert main(a + ["--resume"]) == 0
    assert calls == ["K1"]                                 # 指紋不一致 → 再処理されるべき


def test_オプション変更後のresumeは完了kwを再処理する(tmp_path, monkeypatch):
    src, inp, _ = _setup(tmp_path)
    out = tmp_path / "o"
    a = ["--input", str(inp), "--output", str(out), "--source-root", str(src)]
    assert main(a) == 0

    calls = _spy_finalize(monkeypatch)
    # 行に影響するオプション（min-specificity）を変えて resume
    assert main(a + ["--resume", "--min-specificity", "5"]) == 0
    assert calls == ["K1"]                                 # 指紋不一致 → 再処理されるべき


def test_入力もオプションも不変ならresumeはスキップする(tmp_path, monkeypatch):
    src, inp, _ = _setup(tmp_path)
    out = tmp_path / "o"
    a = ["--input", str(inp), "--output", str(out), "--source-root", str(src)]
    assert main(a) == 0

    calls = _spy_finalize(monkeypatch)
    assert main(a + ["--resume"]) == 0
    assert calls == []                                     # 不変 → 実スキップ（回帰防止）
