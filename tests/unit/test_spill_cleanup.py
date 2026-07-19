"""A8: 起動時に stale な ga_edges_* を掃除する。"""
import subprocess
import sys

from grep_analyzer import spill


def test_stale_edge_tempを掃除(tmp_path):
    stale = tmp_path / "ga_edges_old.tsv"
    stale.write_text("x\n", encoding="utf-8")
    removed = spill.cleanup_stale_edge_files(tmp_path)
    assert not stale.exists()
    assert removed >= 1


def _dead_pid() -> int:
    # 即終了させ reap した PID＝確実に死んでいる PID。
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_並行runの生存スピルファイルは削除しない(tmp_path):
    # cleanup は共有 temp で他 run の「生存中」スピルを消してはならない
    # （消すと当該 run が sorted_unique で FileNotFoundError＝run を落とす）。
    # スピル名に埋めた PID が「別プロセスかつ生存中」なら保全する。
    live_other = tmp_path / "ga_edges_1_live.tsv"        # PID 1(init) は常に生存・自分とは別
    live_other.write_text("x\n", encoding="utf-8")
    dead = tmp_path / f"ga_edges_{_dead_pid()}_x.tsv"    # 死んだ PID＝stale 残骸
    dead.write_text("x\n", encoding="utf-8")
    legacy = tmp_path / "ga_edges_old.tsv"               # PID 無しレガシー＝stale 扱い
    legacy.write_text("x\n", encoding="utf-8")

    removed = spill.cleanup_stale_edge_files(tmp_path)

    assert live_other.exists(), "生存中の別 run のスピルを消してはならない"
    assert not dead.exists() and not legacy.exists()     # 残骸は掃除する
    assert removed >= 2


def test_自PIDの生存スピルも保全する_自己破壊防止(tmp_path):
    # 起動 cleanup が「自 PID＝stale」として消す設計だと、もし cleanup より前に
    # 自 run がスピルしていた場合に自分のファイルを消して自滅する（呼出順依存の脆さ）。
    # 生存中の PID は自他を問わず保全する（自ファイルの掃除は close() の責務）。
    import os
    mine = tmp_path / f"ga_edges_{os.getpid()}_live.tsv"   # 自 PID＝生存中
    mine.write_text("x\n", encoding="utf-8")
    spill.cleanup_stale_edge_files(tmp_path)
    assert mine.exists(), "生存中の自 PID スピルを起動 cleanup が消してはならない"


def test_PID再利用の残骸はstarttime不一致でstale扱いする(tmp_path):
    # 生存 PID でも starttime が異なれば「死んだ run の残骸を無関係プロセスが
    # 誤保全している」状態なので掃除する。自プロセスの PID を借りて再現する。
    import os
    from grep_analyzer.spill import _proc_starttime, cleanup_stale_edge_files
    pid = os.getpid()
    start = _proc_starttime(pid)
    if start is None:
        import pytest
        pytest.skip("/proc が無い環境では starttime 判定は無効")
    stale = tmp_path / f"ga_edges_{pid}-{int(start) + 1}_x.tsv"
    stale.write_text("", "utf-8")
    live = tmp_path / f"ga_edges_{pid}-{start}_y.tsv"
    live.write_text("", "utf-8")
    removed = cleanup_stale_edge_files(tmp_path)
    assert removed == 1
    assert not stale.exists()
    assert live.exists()
