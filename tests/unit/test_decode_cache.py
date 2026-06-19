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


def test_symlink経由でもrealpath正規化で同一エントリを共有する(tmp_path):
    import os
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "real.c", b"int x;\n")
    link = tmp_path / "link.c"
    os.symlink(src, link)
    meta = ("int x;\n", "utf-8", False, "c", "bourne")
    cache.put(str(src), meta)                       # 実体パスで put
    assert cache.get(str(link)) == meta             # symlink 経由でも hit（#2）


def test_本文がtruncatedなアーティファクトはmissとして弾き削除する(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "a.c", b"int x;\n")
    cache.put(str(src), ("HELLO WORLD", "utf-8", False, "c", "bourne"))
    art = next((tmp_path / "cache").glob("*.dca"))
    raw = art.read_bytes()
    nl = raw.find(b"\n")
    art.write_bytes(raw[:nl + 1] + b"HELL")          # 本文だけ切り詰め（ヘッダの blen と不一致）
    assert cache.get(str(src)) is None               # truncated は trust しない（#8）
    assert not art.exists()                          # 破損は削除（L-2）


def test_起動時に残存tempを掃除する(tmp_path):
    cdir = tmp_path / "cache"
    cdir.mkdir()
    stale = cdir / "ga_dca_orphan.tmp"
    stale.write_bytes(b"leftover")
    DecodeCache(cdir)                                 # __init__ で sweep（R-2）
    assert not stale.exists()


def test_max_bytes超過時に古いアーティファクトをLRU退避する(tmp_path):
    import os
    cache = DecodeCache(tmp_path / "cache", max_bytes=4000)
    metas = []
    for i in range(6):
        s = _src(tmp_path, f"f{i}.c", b"x" * 10)
        os.utime(str(s), ns=(1_000_000_000 + i, 1_000_000_000 + i))
        cache.put(str(s), ("Y" * 1500, "utf-8", False, "c", "bourne"))
    total = sum(p.stat().st_size for p in (tmp_path / "cache").glob("*.dca"))
    assert total <= 4000                             # 上限を超えない（R-1）


def test_put失敗はput_failuresを加算し例外を伝播しない(tmp_path, monkeypatch):
    import tempfile as _t
    from grep_analyzer import decode_cache as dc
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "a.c", b"int x;\n")
    monkeypatch.setattr(dc.tempfile, "mkstemp",
                        lambda **kw: (_ for _ in ()).throw(OSError("disk full")))
    cache.put(str(src), ("X", "utf-8", False, "c", "bourne"))   # 落ちない
    assert cache.put_failures == 1
