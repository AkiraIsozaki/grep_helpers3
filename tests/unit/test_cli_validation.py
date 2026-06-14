"""A3: 不在 --input と不正な数値オプションを明示エラー（非0終了）にする。"""
import pytest

from grep_analyzer import cli


def test_input不在は明示エラー(tmp_path):
    with pytest.raises(SystemExit) as ei:
        cli.main(["--input", str(tmp_path / "nope"),
                  "--output", str(tmp_path / "o"),
                  "--source-root", str(tmp_path)])
    assert ei.value.code != 0


def test_jobs0は明示エラー(tmp_path):
    (tmp_path / "in").mkdir()
    with pytest.raises(SystemExit) as ei:
        cli.main(["--input", str(tmp_path / "in"),
                  "--output", str(tmp_path / "o"),
                  "--source-root", str(tmp_path), "--jobs", "0"])
    assert ei.value.code != 0


def test_source_root不在は明示エラー(tmp_path):
    (tmp_path / "in").mkdir()
    with pytest.raises(SystemExit) as ei:
        cli.main(["--input", str(tmp_path / "in"),
                  "--output", str(tmp_path / "o"),
                  "--source-root", str(tmp_path / "nope")])
    assert ei.value.code != 0


def test_max_depth負値は明示エラー(tmp_path):
    (tmp_path / "in").mkdir()
    with pytest.raises(SystemExit) as ei:
        cli.main(["--input", str(tmp_path / "in"),
                  "--output", str(tmp_path / "o"),
                  "--source-root", str(tmp_path), "--max-depth", "-1"])
    assert ei.value.code != 0


def test_max_rows_per_part0は明示エラー(tmp_path):
    (tmp_path / "in").mkdir()
    with pytest.raises(SystemExit) as ei:
        cli.main(["--input", str(tmp_path / "in"),
                  "--output", str(tmp_path / "o"),
                  "--source-root", str(tmp_path), "--max-rows-per-part", "0"])
    assert ei.value.code != 0


# 負値・degenerate な数値はサイレントに劣化出力を出さず明示エラーにする
# （特に --memory-limit 負値は item 予算が負になり 0 件でも超過扱い＝常時最大縮退、
#  --max-file-bytes 負値は全ファイルが large 扱いで空出力になる）。
@pytest.mark.parametrize("opt,val", [
    ("--memory-limit", "-1"),
    ("--min-specificity", "-1"),
    ("--max-file-bytes", "-1"),
    ("--max-symbols", "0"),
    ("--max-paths", "0"),
    ("--max-passes", "0"),
])
def test_不正な数値オプションは明示エラー(tmp_path, opt, val):
    (tmp_path / "in").mkdir()
    with pytest.raises(SystemExit) as ei:
        cli.main(["--input", str(tmp_path / "in"),
                  "--output", str(tmp_path / "o"),
                  "--source-root", str(tmp_path), opt, val])
    assert ei.value.code != 0


def test_memory_limit0は許容_最大縮退の意図的指定(tmp_path):
    # --memory-limit 0 は priority-1 最大縮退として意図的に許容する（負値のみ拒否）。
    (tmp_path / "in").mkdir()
    rc = cli.main(["--input", str(tmp_path / "in"),
                   "--output", str(tmp_path / "o"),
                   "--source-root", str(tmp_path), "--memory-limit", "0"])
    assert rc == 0


def test_stoplist不在は明示エラー(tmp_path):
    (tmp_path / "in").mkdir()
    with pytest.raises(SystemExit) as ei:
        cli.main(["--input", str(tmp_path / "in"),
                  "--output", str(tmp_path / "o"),
                  "--source-root", str(tmp_path),
                  "--stoplist", str(tmp_path / "nope.txt")])
    assert ei.value.code != 0
