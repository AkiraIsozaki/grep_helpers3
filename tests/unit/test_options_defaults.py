"""A10/A11: 既定値が EngineOptions に集約され、CLI 既定と一致する。テスト専用フックは test_only metadata で明示。"""
import dataclasses

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
    excluded = {"exclude", "spill_dir", "stoplist_path", "lang_map", "include",
                "force_chunks", "force_spill"}
    for f in dataclasses.fields(EngineOptions):
        if f.name in excluded:
            continue
        assert getattr(cli_opts, f.name) == getattr(base, f.name), f.name


def test_テスト専用フックはtest_only明示():
    fields = {f.name: f for f in dataclasses.fields(EngineOptions)}
    for name in ("force_chunks", "force_spill"):
        assert fields[name].metadata.get("test_only") is True, name
