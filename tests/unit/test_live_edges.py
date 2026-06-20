"""capped 端のエッジ除外＋sorted_unique の単一 materialize（#G/#N）。"""

from grep_analyzer.fixedpoint._finalize import _uncapped_edges
from grep_analyzer.provenance import Occurrence


class _FakeEdgeStore:
    def __init__(self, edges):
        self._edges = edges
        self.calls = 0

    def sorted_unique(self):
        self.calls += 1                 # 二重評価検出用
        return list(self._edges)


class _FakeState:
    def __init__(self, edges, capped):
        self.edge_store = _FakeEdgeStore(edges)
        self.capped = capped


def test_capped端を持つエッジは両端で一貫除外される():
    p = Occurrence("PARENT", "a.c", 1)
    c = Occurrence("CHILD", "b.c", 2)
    q = Occurrence("OK1", "c.c", 3)
    r = Occurrence("OK2", "d.c", 4)
    st = _FakeState([(p, c), (q, r)], capped={"PARENT"})
    edges = _uncapped_edges(st)
    assert (q, r) in edges
    assert (p, c) not in edges          # parent capped のエッジも除外（非対称解消）


def test_sorted_uniqueは1度だけ評価される():
    q = Occurrence("OK1", "c.c", 3)
    r = Occurrence("OK2", "d.c", 4)
    st = _FakeState([(q, r)], capped=set())
    _uncapped_edges(st)
    assert st.edge_store.calls == 1     # spill 時のディスク再パース二重化を防ぐ（#N）
