"""A10/A11: 既定値が EngineOptions に集約され、CLI 既定と一致する。テスト専用フックは test_only metadata で明示。"""
import dataclasses
import os

from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.pipeline import _default_opts
from grep_analyzer.cli import _build_opts


def test_引数なしEngineOptionsが構築できる():
    # 必須 3 系（input/output/source_root は EngineOptions の対象外）以外は既定で構築可
    opts = EngineOptions()
    assert opts.max_depth == 10
    assert opts.min_specificity == 2
    assert opts.max_paths == 1000


def test_CLI既定とdataclass既定が一致():
    # 全フィールドを走査し dataclass 既定と CLI 既定の drift を検知（§6.1 drift 防止ゲート）。
    # CLI 都合で別値を渡すフィールドと test_only フックのみ明示除外する。
    cli_opts = _build_opts(["--input", "i", "--output", "o", "--source-root", "s"])
    base = EngineOptions()
    # exclude: CLI/pipeline は DEFAULT_EXCLUDE を明示渡し（dataclass 既定 [] とは別・設計どおり）。
    # spill_dir/stoplist_path/lang_map/include: CLI が固有に組み立てるため parity 対象外。
    # jobs/progress: CLI 既定は auto(CPU数)/on（対話利用の UX・出力バイト不変）。
    # ライブラリ既定は 1/off のまま据え置き（テスト・組込み利用で暗黙並列や stderr 出力をしない）。
    excluded = {"exclude", "spill_dir", "stoplist_path", "lang_map", "include",
                "force_chunks", "force_spill", "jobs", "progress"}
    for f in dataclasses.fields(EngineOptions):
        if f.name in excluded:
            continue
        assert getattr(cli_opts, f.name) == getattr(base, f.name), f.name


def test_CLI既定はjobs自動並列とprogress_on():
    # 大規模コーパスでの実用性のため CLI 既定は jobs=CPU数・progress=on。
    # どちらも出力（TSV/manifest/diagnostics）はバイト不変（progress は stderr のみ）。
    opts = _build_opts(["--input", "i", "--output", "o", "--source-root", "s"])
    assert opts.jobs == (os.cpu_count() or 1)
    assert opts.progress == "on"


def test_CLIのjobsとprogressは明示指定が優先される():
    opts = _build_opts(["--input", "i", "--output", "o", "--source-root", "s",
                        "--jobs", "1", "--progress", "off"])
    assert opts.jobs == 1
    assert opts.progress == "off"


def test_テスト専用フックはtest_only明示():
    fields = {f.name: f for f in dataclasses.fields(EngineOptions)}
    for name in ("force_chunks", "force_spill"):
        assert fields[name].metadata.get("test_only") is True, name
