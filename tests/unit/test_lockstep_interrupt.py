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


def test_prefilter無効化はdiagnosticsに記録される(tmp_path, monkeypatch):
    # --use-ripgrep 明示でも rg が壊れていれば黙って全件走査に縮退していた。
    # ON になったことは記録されるのに効かなかったことが残らない非対称を塞ぐ。
    from grep_analyzer import ripgrep
    from grep_analyzer.diagnostics import Diagnostics
    from grep_analyzer.fixedpoint import run_fixedpoint
    from tests.unit.test_fixedpoint import _mk, _opts, _seed

    monkeypatch.setattr(ripgrep, "_resolve_rg", lambda: None)
    src = _mk(tmp_path, {"C.java": "class C { static final int PF_K = 1; }\n",
                         "U.java": "class U { int x = PF_K; }\n"})
    seed = _seed("PF_K", "java", "C.java", 1, "static final int PF_K = 1;")
    diag = Diagnostics()
    hits = run_fixedpoint([seed], src, _opts(max_depth=1, use_ripgrep=True), diag)
    assert any(h.file == "U.java" for h in hits)         # 全件走査へ縮退し出力は正しい
    assert diag.counts().get("prefilter_disabled", 0) >= 1
