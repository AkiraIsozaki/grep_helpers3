"""ChaseState: run_fixedpoint の局所状態をデータクラスにまとめる。

main process でのみ保持・更新する（multiprocessing worker には渡さない）。
worker には (relpath, abspath, symbol_list, lang_map, fallback) のプリミティブのみ渡す
（pickle 制約と決定性維持のため）。
"""

from dataclasses import dataclass, field
from pathlib import Path

from grep_analyzer.budget import MemoryBudget
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.decode_cache import DecodeCache
from grep_analyzer.fixedpoint._encmemo import EncMemo
from grep_analyzer.fixedpoint._options import EngineOptions
from grep_analyzer.provenance import Occurrence, ProvenanceGraph
from grep_analyzer.spill import EdgeStore
from grep_analyzer.stoplist import SymbolPolicy


@dataclass
class ChaseState:
    """不動点反復の全状態を保持する。main process が専有する。

    `introducers`: シンボル -> 発見元 Occurrence 群
    `symbol_kind`: シンボル -> kind（constant/var/getter/setter）
    `symbol_hop`: シンボル -> 投入 hop 番号（決定性キー）
    `chase_active`/`chase_done`: chase 対象（constant/var）の active/done 集合
    `terminal_active`/`terminal_done`: terminal 対象（getter/setter）の集合
    `capped`: --memory-limit 等で除外されたシンボル
    `rel_to_abs`: walk 結果（relpath → abspath）
    `encoding_of`: relpath → (encoding, replaced)。scan 結果から随時更新
    `*_logged`: 同一事象の重複 diagnostics 抑止用
    """

    source_root: Path
    options: EngineOptions
    diagnostics: Diagnostics
    policy: SymbolPolicy
    budget: MemoryBudget
    graph: ProvenanceGraph
    edge_store: EdgeStore
    keyword: str
    introducers: dict[str, list[Occurrence]] = field(default_factory=dict)
    symbol_kind: dict[str, str] = field(default_factory=dict)
    symbol_hop: dict[str, int] = field(default_factory=dict)
    chase_active: set[str] = field(default_factory=set)
    chase_done: set[str] = field(default_factory=set)
    terminal_active: set[str] = field(default_factory=set)
    terminal_done: set[str] = field(default_factory=set)
    capped: set[str] = field(default_factory=set)
    rel_to_abs: dict[str, Path] = field(default_factory=dict)
    encoding_of: dict[str, tuple[str, bool]] = field(default_factory=dict)
    enc_memo: "EncMemo | None" = None
    decode_cache: "DecodeCache | None" = None
    spill_logged: bool = False
    no_expand_logged: set[str] = field(default_factory=set)
    replaced_logged: set[str] = field(default_factory=set)
    maxdepth_logged: set[Occurrence] = field(default_factory=set)
