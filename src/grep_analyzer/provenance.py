"""来歴グラフと chain 正規形。単純パスのみ列挙。"""

from bisect import insort
from dataclasses import dataclass

from grep_analyzer.diagnostics import Diagnostics


@dataclass(frozen=True, order=True)
class Occurrence:
    """ヒット出現＝来歴グラフのノードである。order=True で決定的ソート可能。"""

    symbol: str
    relpath: str
    lineno: int


def _hop(o: Occurrence) -> str:
    """ホップ表記 `symbol@relpath:lineno`。"""
    return f"{o.symbol}@{o.relpath}:{o.lineno}"


class ProvenanceGraph:
    """発見元→発見の有向グラフを表す。種から各ヒットへの単純パスを chain 化する。"""

    def __init__(self) -> None:
        self._seeds: set[Occurrence] = set()
        self._seed_loc: set[tuple[str, int]] = set()
        self._adj: dict[Occurrence, list[Occurrence]] = {}
        # _adj のリスト線形走査（membership）は hot ノードで O(k²) になるため、
        # 重複判定専用の set を併走させる（リスト＝決定的順序の正、set＝判定のみ）。
        self._adj_seen: dict[Occurrence, set[Occurrence]] = {}
        # 祖先枝刈り用の逆隣接（child→parents）。add_edge で無効化し遅延再構築する。
        self._reverse_adj: dict[Occurrence, list[Occurrence]] | None = None

    def add_seed(self, occ: Occurrence) -> None:
        """起点（direct 相当）を登録。物理行も seed として記録。"""
        self._seeds.add(occ)
        self._seed_loc.add((occ.relpath, occ.lineno))

    def is_seed_location(self, relpath: str, lineno: int) -> bool:
        """(relpath,lineno) が direct seed 物理行か（間接再出力の除外判定）。"""
        return (relpath, lineno) in self._seed_loc

    def add_edge(self, parent: Occurrence, child: Occurrence) -> None:
        """発見元 parent → 発見 child のエッジを追加（決定的順序を維持）。

        insort は「append + sort」と同じ昇順リストを維持しつつ挿入 O(k) に抑える
        （sort の O(k log k) と set の O(1) membership で hot ノードの O(k²) を除去）。
        """
        seen = self._adj_seen.setdefault(parent, set())
        if child not in seen:
            seen.add(child)
            insort(self._adj.setdefault(parent, []), child)
            self._reverse_adj = None          # 祖先枝刈り用の逆隣接を無効化する

    def _ancestors_of(self, target: Occurrence) -> set[Occurrence]:
        """target へ到達し得るノード集合（target 自身を含む）を逆方向 BFS で返す。

        chains_to の DFS をこの集合内に枝刈りする。max_paths は「target への到達パス数」
        にしか効かないため、枝刈りが無いと到達不能な部分グラフを max_depth まで
        総当たりで歩き、fan-out の大きい来歴で finalize が終わらなくなる。
        コストは target の祖先部分グラフに比例する（全グラフではない）。
        """
        if self._reverse_adj is None:
            reverse_adj: dict[Occurrence, list[Occurrence]] = {}
            for parent, children in self._adj.items():
                for child in children:
                    reverse_adj.setdefault(child, []).append(parent)
            self._reverse_adj = reverse_adj
        reached = {target}
        frontier = [target]
        while frontier:
            node = frontier.pop()
            for parent in self._reverse_adj.get(node, ()):
                if parent not in reached:
                    reached.add(parent)
                    frontier.append(parent)
        return reached

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
        # target の祖先集合で DFS を枝刈りする。到達不能な部分グラフは歩かない
        # （その枝で従来出ていた prov_max_depth/prov_cycle_cut 診断も出ない。
        # 出力 chain には無関係な探索ノイズであり、探索量の保証を優先する）。
        allowed = self._ancestors_of(target)
        for seed in sorted(self._seeds):
            if len(results) >= limit:
                break
            if seed not in allowed:
                continue
            # visited_symbols は空で開始する（seed と同名 symbol への辺を単純パスとして許容）。
            self._iter_dfs(seed, target, max_depth, limit, diag, results, allowed)
        results = sorted(set(results))
        if len(results) > max_paths:
            diag.add("prov_path_capped", f"{_hop(target)}\t>={max_paths}")
            results = results[:max_paths]
        return results

    def _iter_dfs(self, seed, target, max_depth, limit, diag, results, allowed) -> None:
        """前順再帰 DFS を明示スタックで反復化する（制御フロー・診断順を厳密保持）。

        各フレーム = (node, path, visited_occ, visited_sym, neighbor_iter)。
        _visit が前順の到達処理（target 収集 / max_depth cut 診断）を担い、seed と
        各子で同一に呼ぶことで、cut 診断と子孫探索の interleave が再帰版と同順になる。
        `allowed`（target の祖先集合）外の子へは降りない（到達不能枝の総当たり防止）。
        """
        if len(results) >= limit:
            return

        def _visit(path) -> bool:
            """末端 occ の前順到達処理。target なら results へ収集し、深さ超過なら
            cut 診断を出す。子孫を展開してよいとき True を返す（descend）。"""
            occ = path[-1]
            if occ == target:
                results.append(" -> ".join(_hop(o) for o in path))
                return False
            if len(path) - 1 >= max_depth:
                diag.add("prov_max_depth", _hop(path[0]) + " ... " + _hop(occ))
                return False
            return True

        if not _visit((seed,)):
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
                # 再訪エッジの打ち切りは到達可能性に依らず従来どおり診断する
                # （循環検出は chain 仕様の一部。枝刈りで黙らせない）。
                diag.add("prov_cycle_cut", _hop(node) + " -> " + _hop(next_occ))
                continue
            if next_occ not in allowed:          # target へ到達し得ない未訪問枝は降りない
                continue
            child_path = path + (next_occ,)
            if not _visit(child_path):
                continue
            stack.append((next_occ, child_path, vocc | {next_occ},
                          vsym | {next_occ.symbol},
                          iter(self._adj.get(next_occ, []))))
