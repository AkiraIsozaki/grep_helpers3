from grep_analyzer.decode_cache import DecodeCache
from grep_analyzer.fixedpoint import _scan


def test_meta_cachedはdecode_cacheにhitすれば再decodeしない(tmp_path, monkeypatch):
    src = tmp_path / "a.c"
    src.write_bytes(b"int x;\n")
    dc = DecodeCache(tmp_path / "cache")
    meta = ("int x;\n", "utf-8", False, "c", "bourne")
    dc.put(str(src), meta)
    calls = {"n": 0}
    real = _scan.decode_bytes
    monkeypatch.setattr(_scan, "decode_bytes",
                        lambda d, c: (calls.__setitem__("n", calls["n"] + 1), real(d, c))[1])
    got = _scan.meta_via_decode_cache(None, dc, str(src), "a.c", src.read_bytes(), {}, ["cp932"])
    assert got == meta
    assert calls["n"] == 0
