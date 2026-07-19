"""src / tests 配下にフェーズ・タスク・版・TODO マーカーを残さない（規約の機械強制）。

コメントだけでなく docstring も検査する（マーカーは docstring に多い）。正規表現は
語境界を効かせて識別子・文字列リテラルへの誤マッチを避ける（`spec_phase` の小文字 phase、
`prev.` 等は非マッチ）。`rev\\.` は全角・半角どちらの括弧が前置されても拾う。
"""
import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
# coding-conventions.md の禁止: フェーズ/版/タスク/TODO マーカー。
_FORBIDDEN = re.compile(
    r"\bPhase\s?\d|\bTask\s?\d|\brev\.\d|\bTODO\b|\bFIXME\b|\bNOTE\(|"
    r"フェーズ\s?\d|タスク\s?\d")


_TESTS = Path(__file__).resolve().parents[1]


def _offenders_in(root: Path) -> list[str]:
    out = []
    for p in root.rglob("*.py"):
        if p.name == "test_no_phase_markers.py":
            continue                        # 検査器自身はファイルごと除外（定義行を含むため）
        if "__pycache__" in p.parts:
            continue
        for i, line in enumerate(p.read_text("utf-8").splitlines(), 1):
            if _FORBIDDEN.search(line):
                out.append(f"{p.relative_to(root)}:{i}: {line.strip()}")
    return out


def test_srcに禁止マーカーが無い():
    offenders = _offenders_in(_SRC)
    assert not offenders, "禁止マーカーが残存:\n" + "\n".join(offenders)


def test_testsに禁止マーカーが無い():
    # 規約は「コードに残さない」であり tests もコード（ファイル名の phase 残存も
    # ここで検出される: docstring/コメントに書けばこのテストが落ちる）。
    offenders = _offenders_in(_TESTS)
    assert not offenders, "禁止マーカーが残存:\n" + "\n".join(offenders)


def test_scriptsに禁止マーカーが無い():
    offenders = _offenders_in(_TESTS.parent / "scripts")
    assert not offenders, "禁止マーカーが残存:\n" + "\n".join(offenders)
