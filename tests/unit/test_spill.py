"""来歴エッジのディスクスピルの仕様（spec §8.2 priority-2・出力透過・決定的）。"""

from grep_analyzer.budget import MemoryBudget
from grep_analyzer.provenance import Occurrence
from grep_analyzer.spill import EdgeStore, parse_edge, serialize_edge


def test_制御文字込みで完全往復可逆():
    p = Occurrence("A\tB\\x", "a\nb.c", 3)
    c = Occurrence("C", "d.c", 9)
    assert parse_edge(serialize_edge(p, c)) == (p, c)


def test_close_はfhクローズ失敗時も一時ファイルをunlinkする(tmp_path):
    # close() が _fh.close() で例外を起こすと unlink がスキップされ一時ファイルが残る。
    # 自PID保全方針では残骸が同一プロセス生存中は回収されないため、close は
    # _fh.close() の成否に依らず必ず unlink を試みる（リーク防止）。
    s = EdgeStore(tmp_path, MemoryBudget(0))
    s.add(Occurrence("A", "a.c", 1), Occurrence("B", "b.c", 2))   # スピル発生
    path = s._path
    assert path.exists()

    class _BoomFH:
        def close(self):
            raise OSError("disk full on close")

    s._fh = _BoomFH()
    try:
        s.close()
    except OSError:
        pass                              # close 自体の例外伝播は許容（_lockstep が握る）
    assert not path.exists()              # それでも一時ファイルは確実に消える


def test_孤立サロゲート名でもスピル退避が落ちず完全往復可逆(tmp_path):
    # SJIS 等の非UTF-8ファイル名は os.fsdecode（surrogateescape）で孤立サロゲート
    # (U+DC80〜U+DCFF) を含む str になる。strict UTF-8 だと spill 書込/読戻しが
    # UnicodeEncodeError で run 全体を落とす。プロジェクトの「SJIS混在名で落とさない」
    # 不変条件を spill にも適用し、ディスク退避でも完全往復可逆であることを固定する。
    s = EdgeStore(tmp_path, MemoryBudget(None))
    s._force_spill_threshold = 1                       # 即ディスク退避させる
    e = (Occurrence("SYM_\udc83", "dir/\udcfffile.c", 4),
         Occurrence("CHILD", "c.c", 9))
    s.add(*e)                                          # ここで strict だと crash
    assert s.spilled is True
    assert list(s.sorted_unique()) == [e]              # サロゲートを保ったまま復元
    s.close()


def test_メモリ内sorted_uniqueはsorted_setと同一かつin_memory_len(tmp_path):
    s = EdgeStore(tmp_path, MemoryBudget(None))
    e1 = (Occurrence("Q", "q.c", 2), Occurrence("H", "h.c", 9))
    e2 = (Occurrence("P", "p.c", 1), Occurrence("H", "h.c", 9))
    for p, c in [e1, e2, e1]:
        s.add(p, c)
    assert s.spilled is False and s.in_memory_len() == 3
    assert list(s.sorted_unique()) == sorted({e1, e2})
    s.close()


def test_unitフック強制スピルでも同一集合同一順序かつin_memory_len0(tmp_path):
    s = EdgeStore(tmp_path, MemoryBudget(None))
    s._force_spill_threshold = 1
    edges = [(Occurrence(f"S{i}", f"s{i}.c", i), Occurrence("H", "h.c", 9))
             for i in (3, 1, 2, 1)]
    for p, c in edges:
        s.add(p, c)
    assert s.spilled is True and s.in_memory_len() == 0
    assert list(s.sorted_unique()) == sorted(set(edges))
    s.close()


def test_maybe_spill_nowは閾値非経由で即スピルし透過(tmp_path):
    s = EdgeStore(tmp_path, MemoryBudget(None))
    e = (Occurrence("A", "a.c", 1), Occurrence("B", "b.c", 2))
    s.add(*e)
    assert s.spilled is False and s._force_spill_threshold is None
    s.maybe_spill_now()
    assert s.spilled is True and s._force_spill_threshold is None  # フック不使用
    assert list(s.sorted_unique()) == [e] and s.in_memory_len() == 0
    s.close()


def test_budget0は1件目でスピルし同一(tmp_path):
    s = EdgeStore(tmp_path, MemoryBudget(0))
    e = (Occurrence("A", "a.c", 1), Occurrence("B", "b.c", 2))
    s.add(*e)
    assert s.spilled is True and s.in_memory_len() == 0
    assert list(s.sorted_unique()) == [e]
    s.close()
