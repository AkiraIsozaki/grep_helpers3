"""来歴グラフと chain 正規形。単純パスのみ列挙。"""

from dataclasses import dataclass

from grep_analyzer.diagnostics import Diagnostics


@dataclass(frozen=True, order=True)
class Occurrence:
    """ヒット出現＝来歴グラフのノード。order=True で決定的ソート可能。"""

    symbol: str
    relpath: str
    lineno: int


def _hop(o: Occurrence) -> str:
    """ホップ表記 `symbol@relpath:lineno`。"""
    return f"{o.symbol}@{o.relpath}:{o.lineno}"


class ProvenanceGraph:
    """発見元→発見の有向グラフ。種から各ヒットへの単純パスを chain 化する。"""

    def __init__(self) -> None:
        self._seeds: set[Occurrence] = set()
        self._seed_loc: set[tuple[str, int]] = set()
        self._adj: dict[Occurrence, list[Occurrence]] = {}

    def add_seed(self, occ: Occurrence) -> None:
        """起点（direct 相当）を登録。物理行も seed として記録。"""
        self._seeds.add(occ)
        self._seed_loc.add((occ.relpath, occ.lineno))

    def is_seed_location(self, relpath: str, lineno: int) -> bool:
        """(relpath,lineno) が direct seed 物理行か（間接再出力の除外判定）。"""
        return (relpath, lineno) in self._seed_loc

    def add_edge(self, parent: Occurrence, child: Occurrence) -> None:
        """発見元 parent → 発見 child のエッジを追加（決定的順序を維持）。"""
        lst = self._adj.setdefault(parent, [])
        if child not in lst:
            lst.append(child)
            lst.sort()

    def chains_to(
        self, target: Occurrence, *, max_depth: int, max_paths: int, diag: Diagnostics
    ) -> list[str]:
        """各 seed から target への単純パスを chain 文字列の決定的リストで返す。

        明示スタックによる反復 DFS で実装し、再帰上限（RecursionError）に構造的に
        依存しない。各スタックフレームは隣接の sorted イテレータを保持し、
        前順再帰 DFS と 1 ステップずつ同一の制御フロー（隣接昇順・cut/max_depth 診断の
        interleave 順）を再現する＝diagnostics emit 順は byte 不変。
        収集本数が max_paths+1 に達した時点で DFS を停止する（+1 は真の超過を判定し
        prov_path_capped の誤発火を防ぐため）。DFS 順は seed sorted・隣接 sort で決定的。
        """
        limit = max_paths + 1
        results: list[str] = []
        for seed in sorted(self._seeds):
            if len(results) >= limit:
                break
            # visited_symbols は空で開始する（seed と同名 symbol への辺を単純パスとして許容）。
            self._iter_dfs(seed, target, max_depth, limit, diag, results)
        results = sorted(set(results))
        if len(results) > max_paths:
            diag.add("prov_path_capped", f"{_hop(target)}\t>={max_paths}")
            results = results[:max_paths]
        return results

    def _iter_dfs(self, seed, target, max_depth, limit, diag, results) -> None:
        """前順再帰 DFS を明示スタックで反復化（制御フロー・診断順を厳密保持）。

        各フレーム = (node, path, visited_occ, visited_sym, neighbor_iter)。
        フレーム push 時に node 到達処理（target / max_depth 判定）を一度だけ行い、
        以後は neighbor_iter を 1 つずつ進めて for ループ 1 反復に対応させる。
        これにより cut 診断と子孫探索の interleave が再帰版と同順になる。
        """
        if len(results) >= limit:
            return
        # seed フレームの到達処理（_dfs 冒頭の target / max_depth 判定に対応）。
        if seed == target:
            results.append(_hop(seed))
            return
        if 0 >= max_depth:                       # len(path)-1 == 0
            diag.add("prov_max_depth", _hop(seed) + " ... " + _hop(seed))
            return
        stack = [(seed, (seed,), frozenset({seed}), frozenset(),
                  iter(self._adj.get(seed, [])))]
        while stack:
            if len(results) >= limit:
                return
            node, path, vocc, vsym, it = stack[-1]
            next_occ = next(it, None)
            if next_occ is None:                 # この node の隣接を処理し切った
                stack.pop()
                continue
            if next_occ in vocc or next_occ.symbol in vsym:
                diag.add("prov_cycle_cut", _hop(node) + " -> " + _hop(next_occ))
                continue
            # 子フレームを push する前に、_dfs 冒頭の到達処理を子に対して実行する。
            child_path = path + (next_occ,)
            if next_occ == target:
                results.append(" -> ".join(_hop(o) for o in child_path))
                continue
            if len(child_path) - 1 >= max_depth:
                diag.add("prov_max_depth",
                         _hop(child_path[0]) + " ... " + _hop(next_occ))
                continue
            stack.append((next_occ, child_path, vocc | {next_occ},
                          vsym | {next_occ.symbol},
                          iter(self._adj.get(next_occ, []))))
