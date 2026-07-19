"""capped 端のエッジ除外（#G）と streaming 供給（list 非実体化）。"""

from grep_analyzer.fixedpoint._finalize import _uncapped_edges_iter
from grep_analyzer.provenance import Occurrence


class _FakeEdgeStore:
    def __init__(self, edges):
        self._edges = edges
        self.calls = 0

    def sorted_unique(self):
        self.calls += 1
        yield from self._edges


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
    edges = list(_uncapped_edges_iter(st))
    assert (q, r) in edges
    assert (p, c) not in edges          # parent capped のエッジも除外（非対称解消）


def test_エッジ供給はstreamingで遅延評価される():
    # 全ユニークエッジの list 実体化は graph 隣接と合わせて多重コピーを常駐させ、
    # スピルの目的（メモリ有界）を消費側で無効化する。iterate するまで
    # sorted_unique を呼ばない（materialize しない）こと。
    q = Occurrence("OK1", "c.c", 3)
    r = Occurrence("OK2", "d.c", 4)
    st = _FakeState([(q, r)], capped=set())
    it = _uncapped_edges_iter(st)
    assert st.edge_store.calls == 0     # 生成時点では未評価（lazy）
    assert list(it) == [(q, r)]
    assert st.edge_store.calls == 1
