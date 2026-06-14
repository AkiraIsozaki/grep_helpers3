"""別プロセス・別 PYTHONHASHSEED でも出力 TSV がバイト同値（クロスプロセス決定性）。

既存の決定性テストは同一プロセス内 2 回（＝同一ハッシュシード）止まりだった。
set/dict 由来の順序が出力に漏れていれば別ハッシュシードでバイトがずれ得るが、
それを捕捉するテストが無かった（核心の約束＝決定性の検証の死角）。本テストは
indirect 追跡・複数 keyword・cp932 復号を含むケースを 2 つの別プロセス
（PYTHONHASHSEED=0 と =1）で走らせ、出力 TSV・manifest のバイト一致を固定する。
"""

import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
_CASE = _REPO / "tests" / "golden" / "cases" / "cp932_indirect_multikw"


def _run(out_dir: Path, hashseed: int) -> None:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(hashseed)        # プロセスごとに別ハッシュシード
    r = subprocess.run(
        [sys.executable, "-m", "grep_analyzer",
         "--input", str(_CASE / "input"),
         "--output", str(out_dir),
         "--source-root", str(_CASE / "src")],
        cwd=str(_SRC), env=env, capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")


def _tsv_manifest(out_dir: Path) -> dict[str, bytes]:
    # TSV と manifest のみ比較する。diagnostics.txt は対象外（resume 等で変動し得るが
    # 本テストは無中断 2 回なので実質同一・ここでは TSV/manifest の決定性に集中する）。
    return {p.name: p.read_bytes()
            for p in sorted(out_dir.iterdir())
            if p.suffix == ".tsv" or p.name.endswith(".manifest.json")}


def test_別プロセス別ハッシュシードでも出力がバイト同値(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _run(a, 0)
    _run(b, 1)
    sa, sb = _tsv_manifest(a), _tsv_manifest(b)
    # 非空・indirect を実際に含む（空出力で vacuously pass しない自己防衛）。
    assert sa, "no TSV/manifest produced"
    assert any(b"indirect:" in v for v in sa.values()), "ケースが indirect を駆動していない"
    assert sa.keys() == sb.keys()
    for name in sa:
        assert sa[name] == sb[name], f"cross-process byte mismatch: {name}"
