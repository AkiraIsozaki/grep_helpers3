"""不動点エンジン系テストの共有ヘルパ（EngineOptions/seed Hit/ソースツリー生成）。

テストモジュール間の直輸入（ヘルパ変更が無関係モジュールを壊す結合）を避けるため、
ここに集約する。
"""
from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.model import Hit


def make_opts(**kw):
    """テスト既定の EngineOptions を返す（キーワードで上書き可）。"""
    base = dict(max_depth=5, min_specificity=2, stoplist_path=None, lang_map={},
                include=[], exclude=[], jobs=1, follow_symlinks=False,
                max_file_bytes=1_000_000, max_symbols=1000, max_paths=100,
                memory_limit_mb=None, use_ripgrep=False, max_passes=8,
                progress="off", spill_dir=None, force_chunks=0)
    base.update(kw)
    return EngineOptions(**base)


def make_seed(keyword, language, relpath, lineno, content):
    """direct 相当の seed Hit を生成する。"""
    return Hit(keyword=keyword, language=language, file=relpath, lineno=lineno,
               ref_kind="direct", category="宣言", category_sub="",
               usage_summary=f"宣言 ({language})", via_symbol="",
               chain=f"{keyword}@{relpath}:{lineno}", snippet=content,
               encoding="utf-8", confidence="high")


def make_source_tree(tmp_path, files):
    """{relpath: body} からソースツリーを作り root を返す。"""
    src = tmp_path / "src"
    src.mkdir()
    for relpath, body in files.items():
        f = src / relpath
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, "utf-8")
    return src
