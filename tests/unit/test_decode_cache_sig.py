"""L1: decode_cache の put は呼出側が read した時点の (mtime_ns, size) で保存し、
read と put の間にソースが変わっても「新 sig に旧本文」を載せた stale を正本にしない。"""

import os

from grep_analyzer.decode_cache import DecodeCache
from grep_analyzer.fixedpoint._scan import read_bytes_with_sig


def test_read_bytes_with_sigは本文と同一fdのsigを返す(tmp_path):
    src = tmp_path / "a.c"
    src.write_bytes(b"hello\n")
    raw, sig = read_bytes_with_sig(src)
    st = os.stat(src)
    assert raw == b"hello\n"
    assert sig == (st.st_mtime_ns, st.st_size)


def test_put_は与えたread時sigで保存しstaleを返さない(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = tmp_path / "a.c"
    src.write_bytes(b"OLD\n")
    raw, sig = read_bytes_with_sig(src)            # read 時の bytes/sig
    # read と put の間にソースが書き換わる（live コーパスの TOCTOU を模擬）。
    src.write_bytes(b"NEWDATA\n")
    os.utime(str(src), ns=(9_000_000_000, 9_000_000_000))
    cache.put(str(src), ("OLD\n", "utf-8", False), sig=sig)
    # get は現在のファイル sig（新）でキーを作る。read 時 sig で保存した旧本文は引かない。
    assert cache.get(str(src)) is None
