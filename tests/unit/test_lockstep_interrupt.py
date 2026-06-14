"""A6: 中断時は pool.terminate()、正常完了は close() を呼ぶ。"""
import pytest

from grep_analyzer.budget import MemoryBudget
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.fixedpoint import _lockstep
from grep_analyzer.fixedpoint._state import ChaseState
from grep_analyzer.provenance import ProvenanceGraph
from grep_analyzer.spill import EdgeStore
from grep_analyzer.stoplist import SymbolPolicy
from tests.unit.test_fixedpoint import _opts   # 既存の EngineOptions 構築ヘルパ


class _SpyPool:
    def __init__(self):
        self.closed = self.terminated = self.joined = False

    def close(self):
        self.closed = True

    def terminate(self):
        self.terminated = True

    def join(self):
        self.joined = True


def _minimal_states(tmp_path, opts):
    """run_fixedpoint_multi に渡せる最小 states_by_kw（active 記号 1 つ）。"""
    budget = MemoryBudget(opts.memory_limit_mb)
    st = ChaseState(
        source_root=tmp_path, options=opts, diagnostics=Diagnostics(),
        policy=SymbolPolicy(min_specificity=2, user_stoplist=frozenset()),
        budget=budget, graph=ProvenanceGraph(),
        edge_store=EdgeStore(None, budget), keyword="K")
    st.chase_active = {"alpha"}        # while ループに入るため active を立てる
    return {"K": st}


def test_中断時はterminateが呼ばれる(monkeypatch, tmp_path):
    opts = _opts()                     # A6 は A10 より前なので _opts ヘルパで構築
    spy = _SpyPool()
    monkeypatch.setattr(_lockstep, "make_pool", lambda o, namespace="": spy)

    def boom(*a, **k):
        raise KeyboardInterrupt()

    monkeypatch.setattr(_lockstep, "scan_hop", boom)
    with pytest.raises(KeyboardInterrupt):
        _lockstep.run_fixedpoint_multi(
            _minimal_states(tmp_path, opts), tmp_path, opts, files=[])
    assert spy.terminated is True
    assert spy.closed is False
