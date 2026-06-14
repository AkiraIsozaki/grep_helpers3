from pathlib import Path

from grep_analyzer.decode_cache import DecodeCache


def _src(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_put_then_get_roundtrip(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "a.c", b"int main(){}\n")
    meta = ("int main(){}\n", "utf-8", False, "c", "bourne")
    cache.put(str(src), meta)
    assert cache.get(str(src)) == meta


def test_get_miss_returns_none(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "a.c", b"x\n")
    assert cache.get(str(src)) is None


def test_invalidated_on_mtime_change(tmp_path):
    import os
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "a.c", b"old\n")
    cache.put(str(src), ("OLD", "utf-8", False, "c", "bourne"))
    assert cache.get(str(src)) == ("OLD", "utf-8", False, "c", "bourne")
    src.write_bytes(b"newcontent\n")
    os.utime(str(src), ns=(2_000_000_000, 2_000_000_000))
    assert cache.get(str(src)) is None


def test_body_with_newlines_roundtrips(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "b.sql", b"a\nb\nc\n")
    meta = ("行1\n行2\n末尾なし", "cp932", True, "sql", "bourne")
    cache.put(str(src), meta)
    assert cache.get(str(src)) == meta


def test_missing_source_put_is_noop(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    cache.put(str(tmp_path / "does_not_exist"), ("X", "utf-8", False, "c", "bourne"))
    assert cache.get(str(tmp_path / "does_not_exist")) is None


def test_concurrent_puts_idempotent(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "c.c", b"same\n")
    meta = ("same\n", "utf-8", False, "c", "bourne")
    for _ in range(20):
        cache.put(str(src), meta)
    assert cache.get(str(src)) == meta
