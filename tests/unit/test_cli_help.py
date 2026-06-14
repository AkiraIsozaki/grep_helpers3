"""A2: --help が全オプションの説明を出し、--progress が choices で検証される。"""
import pytest

from grep_analyzer import cli


def test_helpに主要オプションの説明が出る(capsys):
    with pytest.raises(SystemExit):
        cli._make_parser().parse_args(["--help"])
    out = capsys.readouterr().out
    assert "--resume" in out
    assert "完了済" in out          # --resume の help 文（説明が存在する証拠）
    assert "--memory-limit" in out


def test_progressは不正値を弾く():
    with pytest.raises(SystemExit):
        cli._make_parser().parse_args(
            ["--input", "i", "--output", "o", "--source-root", "s",
             "--progress", "verbose"])
