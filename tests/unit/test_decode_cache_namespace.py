"""decode_cache の namespace が復号を左右する設定を取り込むことを検証する（C1）。

共有 --decode-cache-dir で run をまたいで再利用する際、encoding_fallback や
lang_map を変えたら別アーティファクトとしてミスしなければならない。さもないと
前 run の復号テキスト・言語判定が後 run にヒットして汚染する。
"""

from dataclasses import replace

from grep_analyzer.fixedpoint._options import EngineOptions
from grep_analyzer.fixedpoint._scan import decode_cache_namespace


def _opts(**kw):
    return replace(EngineOptions(), **kw)


def test_同一設定なら同一namespace():
    a = _opts(encoding_fallback=("cp932", "euc-jp"), lang_map={".inc": "c"})
    b = _opts(encoding_fallback=("cp932", "euc-jp"), lang_map={".inc": "c"})
    assert decode_cache_namespace(a) == decode_cache_namespace(b)


def test_encoding_fallbackが違えばnamespaceが変わる():
    a = _opts(encoding_fallback=("cp932", "euc-jp"))
    b = _opts(encoding_fallback=("euc-jp", "cp932"))
    assert decode_cache_namespace(a) != decode_cache_namespace(b)


def test_lang_mapが違えばnamespaceが変わる():
    a = _opts(lang_map={".inc": "c"})
    b = _opts(lang_map={".inc": "jsp"})
    assert decode_cache_namespace(a) != decode_cache_namespace(b)


def test_fastフラグはnamespaceに反映される():
    a = _opts(fast_encoding=False)
    b = _opts(fast_encoding=True)
    assert decode_cache_namespace(a) != decode_cache_namespace(b)
