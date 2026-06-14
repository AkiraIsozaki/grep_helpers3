from pathlib import Path

from grep_analyzer.decode_cache import DecodeCache


def _src(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_putした内容はgetで同一に取り出せる(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "a.c", b"int main(){}\n")
    meta = ("int main(){}\n", "utf-8", False, "c", "bourne")
    cache.put(str(src), meta)
    assert cache.get(str(src)) == meta


def test_未登録ファイルのgetはNoneを返す(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "a.c", b"x\n")
    assert cache.get(str(src)) is None


def test_ソース更新時はサイズmtime不一致でキャッシュミスする(tmp_path):
    import os
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "a.c", b"old\n")
    cache.put(str(src), ("OLD", "utf-8", False, "c", "bourne"))
    assert cache.get(str(src)) == ("OLD", "utf-8", False, "c", "bourne")
    src.write_bytes(b"newcontent\n")
    os.utime(str(src), ns=(2_000_000_000, 2_000_000_000))
    assert cache.get(str(src)) is None


def test_改行を含む本文も完全に往復する(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "b.sql", b"a\nb\nc\n")
    meta = ("行1\n行2\n末尾なし", "cp932", True, "sql", "bourne")
    cache.put(str(src), meta)
    assert cache.get(str(src)) == meta


def test_存在しないソースへのputは無効でgetもNoneを返す(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    cache.put(str(tmp_path / "does_not_exist"), ("X", "utf-8", False, "c", "bourne"))
    assert cache.get(str(tmp_path / "does_not_exist")) is None


def test_同一内容の多重putは冪等(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "c.c", b"same\n")
    meta = ("same\n", "utf-8", False, "c", "bourne")
    for _ in range(20):
        cache.put(str(src), meta)
    assert cache.get(str(src)) == meta


def test_CRLFや単独CRを含む本文もバイト改変なく往復する(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "crlf.c", b"x\r\ny\r\n")
    meta = ("int a;\r\nint b;\r\n\r行頭CR\rおわり", "cp932", False, "c", "bourne")
    cache.put(str(src), meta)
    assert cache.get(str(src)) == meta          # \r\n も 単独\r も保持
