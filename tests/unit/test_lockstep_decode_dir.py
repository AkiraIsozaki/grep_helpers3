"""run_fixedpoint_multi が decode_cache_dir 未指定時に temp dir を一度だけ解決し
worker 間で共有・後始末することの回帰（#9）。"""

import dataclasses

from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.fixedpoint import _scan, _lockstep


def test_decode_cache_dir未指定でも単一tempを解決しmake_poolへ伝える(tmp_path, monkeypatch):
    seen = {}

    real_make_pool = _scan.make_pool

    def spy_make_pool(opts, namespace=""):
        seen["pool_dir"] = opts.decode_cache_dir
        return None        # jobs<=1 相当（pool 無し）。dir 解決だけ観測する。

    monkeypatch.setattr(_lockstep, "make_pool", spy_make_pool)

    opts = EngineOptions(decode_cache_dir=None)
    # files 空＝走査は即終了。dir 解決と後始末だけを観測する。
    _lockstep.run_fixedpoint_multi({}, tmp_path, opts, files=[])

    assert seen["pool_dir"] is not None, "make_pool に concrete な decode_cache_dir が渡っていない（#9）"
    assert not seen["pool_dir"].exists(), "auto temp dir が後始末されていない（#9 leak）"
