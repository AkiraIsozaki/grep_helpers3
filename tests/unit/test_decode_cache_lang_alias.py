"""decode_cache は realpath をキーに共有するが、language/dialect は relpath 由来で
毎回導出しなければならない（H2: realpath エイリアスによる言語誤判定の回帰防止）。"""

import os

from grep_analyzer.decode_cache import DecodeCache
from grep_analyzer.fixedpoint._encmemo import EncMemo
from grep_analyzer.fixedpoint._scan import meta_via_decode_cache

_FB = ["cp932", "euc-jp", "latin-1"]


def test_realpath共有でも言語はrelpathごとに導出される(tmp_path):
    real = tmp_path / "real.py"
    real.write_bytes(b"x = 1\n")
    link = tmp_path / "link.c"
    os.symlink(real, link)              # realpath(link.c) == realpath(real.py)
    cache = DecodeCache(tmp_path / "cache")
    enc = EncMemo()

    t1, _, _, l1, _ = meta_via_decode_cache(enc, cache, str(real), "real.py",
                                  real.read_bytes(), {}, _FB)
    assert l1 == "python"

    # 同一 realpath を .c 経由で参照しても language は relpath（.c）由来でなければならない。
    # 旧実装はキャッシュ済の python をそのまま返していた。
    t2, _, _, l2, _ = meta_via_decode_cache(enc, cache, str(link), "link.c",
                                  link.read_bytes(), {}, _FB)
    assert l2 == "c"
    assert t2 == "x = 1\n"
