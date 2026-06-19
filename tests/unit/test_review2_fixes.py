"""二次批判レビューで見つかった堅牢性スメルの回帰（F2/F3）。"""

import dataclasses
from pathlib import Path

from grep_analyzer import walk
from grep_analyzer.fixedpoint import _scan
from grep_analyzer.pipeline import _default_opts, run


def test_worker_initはmax_bytesをworker_decode_cacheへ伝える_F3(tmp_path):
    # --jobs>1 で worker が上限を無視すると --decode-cache-max-bytes が効かない。
    _scan._worker_init({}, ["cp932"], 2, str(tmp_path), "", False, 12345)
    assert _scan._WORKER_DECODE_CACHE._max_bytes == 12345


def test_runは古いroot_realpathキャッシュをクリアする_F2(tmp_path):
    # 同一プロセス内の run 跨ぎで stale な root realpath を引かないこと。
    walk._realpath_root.cache_clear()
    walk._realpath_root("/tmp/_ga_stale_sentinel")          # bogus を prime
    src = tmp_path / "src"; src.mkdir()
    (src / "a.sql").write_text("-- c\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "k.grep").write_text("a.sql:1:-- c\n", "utf-8")
    run(input_dir=inp, output_dir=tmp_path / "out", source_root=src,
        opts=dataclasses.replace(_default_opts()))
    # run 入口で clear されていれば sentinel は消え、再呼出は miss になる。
    m0 = walk._realpath_root.cache_info().misses
    walk._realpath_root("/tmp/_ga_stale_sentinel")
    assert walk._realpath_root.cache_info().misses == m0 + 1
