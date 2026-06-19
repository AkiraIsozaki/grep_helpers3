"""非可逆 --output-encoding でも resume の完了判定が成立することを検証する（C3）。

旧実装は data_sha256 を utf-8 原文で計算する一方、resume は part を output_encoding で
読み戻して utf-8 で再計算していたため、cp932 非表現文字（例: U+2603「☃」）が `?` に
置換されると sha が必ず不一致になり、is_complete が恒久 False＝当該 keyword が毎 run
再処理されていた。data_sha256 を「実際に永続化される姿（非可逆置換反映後）」で計算し、
書込側と resume 側を一致させる。
"""

from grep_analyzer import resume
from grep_analyzer.output_writer import finalize
from tests.unit.test_output_writer import _hit, _opts


def test_cp932非表現文字を含む行でもcp932出力のresumeが完了判定真(tmp_path):
    # snippet に cp932 で表現できない文字（右向き矢印 U+2192）を含める。
    rows = [_hit("a.java", 1, "x ☃ y"), _hit("b.java", 2, "ok")]
    opts = _opts(output_encoding="cp932")
    finalize(tmp_path, "K", rows, opts)
    assert resume.is_complete(tmp_path, "K", opts) is True


def test_utf8出力では従来どおりresume完了判定真(tmp_path):
    rows = [_hit("a.java", 1, "x ☃ y")]  # utf-8 では可逆なので従来挙動
    opts = _opts(output_encoding="utf-8-sig")
    finalize(tmp_path, "K", rows, opts)
    assert resume.is_complete(tmp_path, "K", opts) is True
