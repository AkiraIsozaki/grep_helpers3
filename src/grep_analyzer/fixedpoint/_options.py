"""EngineOptions: エンジン挙動パラメータ。

`run_fixedpoint` 経由でエンジン内部で参照される。`fixedpoint/__init__.py`
から `from grep_analyzer.fixedpoint import EngineOptions` で再 export される。
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EngineOptions:
    """エンジン挙動パラメータ。既定値はここが唯一の定義場所。"""

    max_depth: int = 10
    min_specificity: int = 2
    stoplist_path: Path | None = None
    lang_map: dict[str, str] = field(default_factory=dict)
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    jobs: int = 1
    follow_symlinks: bool = False
    max_file_bytes: int = 5_000_000
    max_symbols: int = 100_000
    max_paths: int = 1000
    memory_limit_mb: int | None = None
    use_ripgrep: bool | None = None
    ripgrep_threshold_bytes: int = 1 << 30
    max_passes: int = 8
    progress: str = "off"
    spill_dir: Path | None = None
    force_chunks: int = field(default=0, metadata={"test_only": True})
    force_spill: int = field(default=0, metadata={"test_only": True})  # >0 でエッジ N 件目から強制 spill（テスト専用・本番 0）
    resume: bool = False
    output_encoding: str = "utf-8-sig"
    encoding_fallback: tuple[str, ...] = ("cp932", "euc-jp", "latin-1")
    max_rows_per_part: int = 1_048_575
    diagnostics_detail_limit: int = 1000
