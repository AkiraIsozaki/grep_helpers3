"""diagnostics.txt が --jobs 1 と --jobs N でバイト同値（jobs 決定性ゲート・H7）。

決定性 claim は従来 TSV/manifest のみで守られ、diagnostics.txt の jobs>1 バイト一致を
検証するゲートがどこにも無かった（pipeline.py 自身が「keyword 横断 DETAIL 順の byte
一致は未実現」と認めている）。本テストは indirect 追跡・複数 keyword・cp932 decode_replaced・
symlink dedup・binary skip 等、診断を実際に駆動する golden ケースで jobs=1 と jobs=2 の
diagnostics.txt がバイト同値であることを固定し、並列での診断決定性の回帰を捕捉する。
"""

import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
_CASES = _REPO / "tests" / "golden" / "cases"

# 診断を実際に駆動するケース（indirect / decode_replaced / dedup / binary skip / multi-kw）。
_DRIVE_CASES = [
    "cp932_indirect_multikw",
    "multi_keyword_chain",
    "messy_c_legacy",
    "symlink_dedup",
    "grep_binary_nul",
    "encoding_mixed_tree",
    "source_ctrl_chars",
]


def _run(case: Path, out_dir: Path, jobs: int) -> None:
    r = subprocess.run(
        [sys.executable, "-m", "grep_analyzer",
         "--input", str(case / "input"),
         "--output", str(out_dir),
         "--source-root", str(case / "src"),
         "--jobs", str(jobs)],
        cwd=str(_SRC), capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")


@pytest.mark.parametrize("case_name", _DRIVE_CASES)
def test_diagnosticsはjobs1とjobs2でバイト同値(tmp_path, case_name):
    case = _CASES / case_name
    if not (case / "input").is_dir():
        pytest.skip(f"case not present: {case_name}")
    a, b = tmp_path / "j1", tmp_path / "j2"
    _run(case, a, 1)
    _run(case, b, 2)
    da = (a / "diagnostics.txt").read_bytes()
    db = (b / "diagnostics.txt").read_bytes()
    assert da == db, f"{case_name}: diagnostics.txt が jobs 間でバイト不一致"
