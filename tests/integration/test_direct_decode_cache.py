"""direct 経路が永続デコードキャッシュを共有し二重 decode/言語判定を避ける回帰（#1）。"""

import dataclasses
from pathlib import Path

from grep_analyzer.fixedpoint import _scan
from grep_analyzer.pipeline import _default_opts, run


def _setup(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    # シンボルを生まないコメント行ヒット＝seed 展開・scan・indirect が起きず、
    # 同一ファイルへの decode/言語判定は direct と seed の 2 経路だけに絞られる。
    (src / "a.sql").write_text("-- just a comment line\n", "utf-8")
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "comment.grep").write_text("a.sql:1:-- just a comment line\n", "utf-8")
    return src, inp


def test_direct経路がdecode_cacheを共有し本文decodeを二重に走らせない(tmp_path, monkeypatch):
    src, inp = _setup(tmp_path)
    calls = {"n": 0}
    orig = _scan.decode_with_memo

    def spy(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)

    # 高コストな本文 decode（read→decode_bytes/chardet）は decode_with_memo を通る。
    # direct/seed/scan/finalize の miss 経路はすべてここを通るので差し替えれば全経路を捕捉できる。
    # language/dialect は安価なので hit ごとに relpath から再導出する（H2）が、本文 decode は
    # ファイルにつき 1 回に固定されていなければならない（これが decode_cache の本旨）。
    monkeypatch.setattr(_scan, "decode_with_memo", spy)

    opts = dataclasses.replace(_default_opts(),
                               decode_cache_dir=tmp_path / "dcache")
    rc = run(input_dir=inp, output_dir=tmp_path / "out", source_root=src, opts=opts)
    assert rc == 0
    # direct が decode_cache に put すれば seed は hit し、本文 decode は 1 回で済む。
    # 修正前は direct(キャッシュ非経由)＋seed(miss) で 2 回走っていた。
    assert calls["n"] == 1, f"本文 decode が {calls['n']} 回（direct と seed で二重）"
