"""decode_cache の namespace が復号を左右する設定を取り込むことを検証する（C1）。

共有 --decode-cache-dir で run をまたいで再利用する際、encoding_fallback や fast を
変えたら別アーティファクトとしてミスしなければならない。さもないと前 run の復号テキストが
後 run にヒットして汚染する。

H2 以降、キャッシュ値は (text, enc, replaced) のみで language/dialect は含まない
（hit 毎に relpath から再導出）。よって lang_map は復号結果に影響せず、namespace に
含めない（lang_map だけ変えた run 跨ぎでも decode アーティファクトは正しく共有される）。
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


def test_lang_mapはnamespaceに影響しない():
    # H2 以降 language はキャッシュしないので lang_map は復号アーティファクトに無関係。
    # namespace に含めると lang_map 変更時に decode を不要に全ミスさせる（Obs-B）。
    a = _opts(lang_map={".inc": "c"})
    b = _opts(lang_map={".inc": "jsp"})
    assert decode_cache_namespace(a) == decode_cache_namespace(b)


def test_fastフラグはnamespaceに反映される():
    a = _opts(fast_encoding=False)
    b = _opts(fast_encoding=True)
    assert decode_cache_namespace(a) != decode_cache_namespace(b)
