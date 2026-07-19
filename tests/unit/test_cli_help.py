"""A2: --help が全オプションの説明を出し、--progress が choices で検証される。"""
import pytest

from grep_analyzer import cli


def test_helpに全オプションの説明が出る(capsys):
    parser = cli._make_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    out = capsys.readouterr().out
    # 全登録オプションが help に列挙され、help 文も空でないこと（欠落回帰の防止）。
    for action in parser._actions:
        for opt in action.option_strings:
            assert opt in out, f"help に {opt} が無い"
        if action.option_strings and action.help is None:
            raise AssertionError(f"{action.option_strings[0]} に help 文が無い")
    assert "完了済" in out          # --resume の help 文（説明が存在する証拠）


def test_progressは不正値を弾く():
    with pytest.raises(SystemExit):
        cli._make_parser().parse_args(
            ["--input", "i", "--output", "o", "--source-root", "s",
             "--progress", "verbose"])
