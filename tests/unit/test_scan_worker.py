"""A-5: ワーカ走査の per-file 例外降格（読めないファイルで run 全体を落とさない）。"""

from grep_analyzer import automaton
from grep_analyzer.fixedpoint._scan import _scan_one, file_meta


def test_scan経路の言語判定もdirectと同じ窓でEXEC_SQLを取りこぼさない():
    # direct(pipeline) は 64KiB 窓で言語判定するが、scan/indirect 経路(file_meta)が
    # 4KiB 窓だと、長い preamble 後に EXEC SQL がある .c を direct=proc・indirect=c と
    # 食い違って分類し、同一ファイルの language/usage_summary/snippet 列がブレる。
    # 両経路は同じサンプリング窓で同一に分類しなければならない。
    preamble = "// header comment line\n" * 300            # 4096 字超（約 6900 字）
    text = preamble + "EXEC SQL SELECT 1 INTO :x FROM dual;\n"
    lang = file_meta("a.c", text.encode("utf-8"), {})[3]   # 5-tuple の language
    assert lang == "proc"


def test_読めないファイルは例外でなく空ヒットを返す(tmp_path):
    missing = tmp_path / "ghost.java"            # walk 後に消えた想定（存在しない）
    auto = automaton.build(["K1"])
    rel, enc, replaced, lang, dialect, found = _scan_one(
        "ghost.java", str(missing), auto, {}, ["cp932", "euc-jp", "latin-1"])
    assert rel == "ghost.java"
    assert found == []                            # 例外送出せず空


def test_読めるファイルは従来どおりヒットを返す(tmp_path):
    f = tmp_path / "A.java"
    f.write_text("int K1 = 1;\n", "utf-8")
    auto = automaton.build(["K1"])
    rel, enc, replaced, lang, dialect, found = _scan_one(
        "A.java", str(f), auto, {}, ["cp932", "euc-jp", "latin-1"])
    assert any(sym == "K1" for sym, *_ in found)


def test_read_metaはdecode_cacheにhitすれば再decodeしない(tmp_path, monkeypatch):
    from grep_analyzer.fixedpoint import _scan
    from grep_analyzer.decode_cache import DecodeCache

    src = tmp_path / "a.c"
    src.write_bytes(b"int x;\n")
    dc = DecodeCache(tmp_path / "cache")
    meta = ("int x;\n", "utf-8", False, "c", "bourne")
    dc.put(str(src), meta)

    calls = {"n": 0}
    real = _scan.decode_bytes

    def spy(data, chain):
        calls["n"] += 1
        return real(data, chain)
    monkeypatch.setattr(_scan, "decode_bytes", spy)

    got = _scan._read_meta("a.c", str(src), {}, ["cp932"], None, decode_cache=dc)
    assert got == meta
    assert calls["n"] == 0
