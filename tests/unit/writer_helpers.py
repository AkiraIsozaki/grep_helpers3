"""output_writer/resume 系テストの共有ヘルパ（Hit/EngineOptions/行列生成）。

テストモジュール間の直輸入（ヘルパ変更が無関係モジュールを壊す結合）を避けるため、
ここに集約する。
"""
from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.model import Hit


def make_hit(file, lineno, snippet):
    """finalize 入力用の最小 Hit を生成する。"""
    return Hit(keyword="K", language="java", file=file, lineno=lineno,
               ref_kind="direct", category="c", category_sub="",
               usage_summary="u", via_symbol="", chain="ch",
               snippet=snippet, encoding="utf-8", confidence="low")


def make_writer_opts(**kw):
    """出力系テスト既定の EngineOptions を返す（キーワードで上書き可）。"""
    base = dict(max_depth=10, min_specificity=2, stoplist_path=None,
                lang_map={}, include=[], exclude=[], jobs=1,
                follow_symlinks=False, max_file_bytes=5_000_000,
                max_symbols=100_000, max_paths=1000)
    base.update(kw)
    return EngineOptions(**base)


def make_hits(n):
    """n 行の連番 Hit 列を生成する（part 分割テスト用）。"""
    return [make_hit(f"f{i:05d}.java", i, f"s{i}") for i in range(n)]
