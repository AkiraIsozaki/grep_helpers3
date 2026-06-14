"""§6.1: src 配下に Phase/Task/版/TODO マーカーを残さない（規約の機械強制）。

コメントだけでなく docstring も検査する（マーカーは docstring に多い）。正規表現は
語境界を効かせて識別子・文字列リテラルへの誤マッチを避ける（`spec_phase` の小文字 phase、
`prev.` 等は非マッチ）。`rev\\.` は全角・半角どちらの括弧が前置されても拾う。
"""
import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
# coding-conventions.md の禁止: フェーズ/版/タスク/TODO マーカー。
_FORBIDDEN = re.compile(r"\bPhase\s?\d|\bTask\s?\d|\brev\.\d|\bTODO\b|\bFIXME\b|\bNOTE\(")


def test_srcに禁止マーカーが無い():
    offenders = []
    for p in _SRC.rglob("*.py"):
        for i, line in enumerate(p.read_text("utf-8").splitlines(), 1):
            if _FORBIDDEN.search(line):
                offenders.append(f"{p.relative_to(_SRC)}:{i}: {line.strip()}")
    assert not offenders, "禁止マーカーが残存:\n" + "\n".join(offenders)
