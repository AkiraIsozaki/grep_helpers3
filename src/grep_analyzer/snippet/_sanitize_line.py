"""snippet 行のサニタイズと物理行分解を行う。

物理行分解: 末尾改行由来の人工空要素を 1 個だけ除去する。
区切り衝突エスケープ: 行中の ' \\n ' と同一 4 文字並びの \\ を二重化する。
"""

# _escape_sep は _clamp.py が単一情報源（snippet 最終段で適用するため）。後方互換で再 export。
from grep_analyzer.snippet._clamp import SEP, _escape_sep  # noqa: F401


def _physical_lines(file_text: str) -> list[str]:
    """物理行配列を返す。末尾改行由来の人工空要素を 1 個だけ除去する（物理行定義）。"""
    lines = file_text.split("\n")
    if file_text.endswith("\n") and lines and lines[-1] == "":
        lines = lines[:-1]
    return lines
