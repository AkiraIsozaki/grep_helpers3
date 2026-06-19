"""--fast-encoding のヘルプが euc-jp/cp932 誤復号リスクを明記することを検証する（H1）。

design doc §5 は「fast 短絡は euc-jp ファイルが cp932 strict で誤復号し得る既知
トレードオフ。フラグ説明に明記」と要求している。ヘルプ文がそのリスクに触れる。
"""

from grep_analyzer.cli import _make_parser


def _help_for(dest: str) -> str:
    parser = _make_parser()
    for action in parser._actions:
        if action.dest == dest:
            return action.help or ""
    raise AssertionError(f"action {dest} not found")


def test_fast_encodingヘルプが誤復号リスクに言及する():
    help_text = _help_for("fast_encoding")
    assert "euc-jp" in help_text
    assert "誤復号" in help_text
