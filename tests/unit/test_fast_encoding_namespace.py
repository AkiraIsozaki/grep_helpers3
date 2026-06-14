"""fast と非 fast のキャッシュ名前空間分離を確認するテスト。"""

from grep_analyzer.decode_cache import DecodeCache


def test_fastと非fastは別名前空間でキャッシュが衝突しない(tmp_path):
    src = tmp_path / "a.c"; src.write_bytes(b"x\n")
    a = DecodeCache(tmp_path / "dc", namespace="")
    b = DecodeCache(tmp_path / "dc", namespace="fast")
    a.put(str(src), ("NONFAST", "euc-jp", False, "c", "bourne"))
    b.put(str(src), ("FAST", "cp932", False, "c", "bourne"))
    assert a.get(str(src))[0] == "NONFAST"
    assert b.get(str(src))[0] == "FAST"
