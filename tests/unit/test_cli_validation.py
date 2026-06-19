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


def test_outputがsource_rootと同一は明示エラー(tmp_path):
    # finalize の孤児削除が {kw}.tsv/{kw}.part*.tsv を無条件 unlink するため、
    # source-root と同一 output は既存ソースを破壊し得る（H6）。
    (tmp_path / "in").mkdir()
    with pytest.raises(SystemExit) as ei:
        cli.main(["--input", str(tmp_path / "in"),
                  "--output", str(tmp_path),
                  "--source-root", str(tmp_path)])
    assert ei.value.code != 0


def test_outputがinputと同一は明示エラー(tmp_path):
    (tmp_path / "in").mkdir()
    (tmp_path / "src").mkdir()
    with pytest.raises(SystemExit) as ei:
        cli.main(["--input", str(tmp_path / "in"),
                  "--output", str(tmp_path / "in"),
                  "--source-root", str(tmp_path / "src")])
    assert ei.value.code != 0


@pytest.mark.parametrize("spec", ["garbage", ".inc=", "=c", ".inc=c,bad"])
def test_lang_map不正ペアは黙殺せず明示エラー(tmp_path, spec):
    # `=` 欠落や ext/lang 空のペアを黙ってスキップすると、タイポが無言で無視され
    # 上書きが効かないまま成功終了する（M）。明示エラーで気づけるようにする。
    (tmp_path / "in").mkdir()
    with pytest.raises(SystemExit) as ei:
        cli.main(["--input", str(tmp_path / "in"),
                  "--output", str(tmp_path / "o"),
                  "--source-root", str(tmp_path), "--lang-map", spec])
    assert ei.value.code != 0


def test_lang_map正当なペアは受理(tmp_path):
    (tmp_path / "in").mkdir()
    rc = cli.main(["--input", str(tmp_path / "in"),
                   "--output", str(tmp_path / "o"),
                   "--source-root", str(tmp_path), "--lang-map", ".inc=c,.tpl=jsp"])
    assert rc == 0


def test_diagnostics_detail_limit負値は明示エラー(tmp_path):
    # 負値は diagnostics 側で >0 不成立＝無制限と二重になりヘルプと乖離（M）。
    (tmp_path / "in").mkdir()
    with pytest.raises(SystemExit) as ei:
        cli.main(["--input", str(tmp_path / "in"),
                  "--output", str(tmp_path / "o"),
                  "--source-root", str(tmp_path),
                  "--diagnostics-detail-limit", "-1"])
    assert ei.value.code != 0


def test_stoplist不在は明示エラー(tmp_path):
    (tmp_path / "in").mkdir()
    with pytest.raises(SystemExit) as ei:
        cli.main(["--input", str(tmp_path / "in"),
                  "--output", str(tmp_path / "o"),
                  "--source-root", str(tmp_path),
                  "--stoplist", str(tmp_path / "nope.txt")])
    assert ei.value.code != 0


def test_decode_cache_max_bytes_0は明示エラー(tmp_path):
    (tmp_path / "in").mkdir()
    with pytest.raises(SystemExit) as ei:
        cli.main(["--input", str(tmp_path / "in"),
                  "--output", str(tmp_path / "o"),
                  "--source-root", str(tmp_path), "--decode-cache-max-bytes", "0"])
    assert ei.value.code != 0
