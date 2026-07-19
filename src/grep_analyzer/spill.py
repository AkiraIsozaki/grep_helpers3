"""来歴エッジをディスクへスピルする。予算内はメモリに保持し、超過でディスクへ追記退避する。

sorted_unique は in-memory/spill いずれでも sorted(set(edges)) と同一である（決定的）。
スピル済の確定は全件をメモリへ読み戻さず、チャンクソート済み run のマージで
ストリーミングする（メモリ有界＝スピルの目的を確定段でも保つ）。
in_memory_len はメモリ常駐数を返す（スピル後 0）。maybe_spill_now は engine 用で
内部 _spill_now を直呼びする（_force_spill_threshold は unit テスト専用）。
"""

import heapq
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

from grep_analyzer.provenance import Occurrence

# 外部マージの 1 run に載せるエッジ数（sorted_unique のピークメモリ上限を決める）。
_SORT_CHUNK_EDGES = 200_000

_ESC = {"\\": "\\\\", "\t": "\\t", "\n": "\\n", "\r": "\\r"}
_UNESC = {"\\\\": "\\", "\\t": "\t", "\\n": "\n", "\\r": "\r"}


def _escape(s: str) -> str:
    return "".join(_ESC.get(ch, ch) for ch in s)


def _unescape(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            two = s[i:i + 2]
            if two in _UNESC:
                out.append(_UNESC[two])
                i += 2
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def serialize_edge(p: Occurrence, c: Occurrence) -> str:
    """1 エッジを 6 フィールドのタブ区切り1行へ変換する（制御文字エスケープ）。"""
    return "\t".join((_escape(p.symbol), _escape(p.relpath), str(p.lineno),
                      _escape(c.symbol), _escape(c.relpath), str(c.lineno)))


def parse_edge(line: str) -> tuple[Occurrence, Occurrence]:
    """serialize_edge の逆変換（制御文字を含めて round-trip する）。"""
    f = line.rstrip("\n").split("\t")
    return (Occurrence(_unescape(f[0]), _unescape(f[1]), int(f[2])),
            Occurrence(_unescape(f[3]), _unescape(f[4]), int(f[5])))


class EdgeStore:
    """来歴エッジを予算内メモリ、超過でディスクへ退避して保持する。"""

    def __init__(self, spill_dir: Path | None, budget) -> None:
        self._mem: list[tuple[Occurrence, Occurrence]] = []
        self._budget = budget
        self._dir = Path(spill_dir) if spill_dir is not None else Path(tempfile.gettempdir())
        self._fh = None
        self._path: Path | None = None
        self.spilled = False
        self._force_spill_threshold: int | None = None  # unit テスト専用

    def add(self, p: Occurrence, c: Occurrence) -> None:
        """1 エッジを追加する。予算/unit フック超過で以降はスピルへ切り替える。"""
        if self.spilled:
            self._fh.write(serialize_edge(p, c) + "\n")
            return
        self._mem.append((p, c))
        self.maybe_spill()

    def in_memory_len(self) -> int:
        """メモリ常駐エッジ数を返す（スピル後は 0）。"""
        return 0 if self.spilled else len(self._mem)

    def maybe_spill(self) -> None:
        """予算/unit フック超過ならスピルする。"""
        if self.spilled:
            return
        thr = self._force_spill_threshold
        over = (thr is not None and len(self._mem) >= thr) or \
               self._budget.exceeded(len(self._mem))
        if over:
            self._spill_now()

    def maybe_spill_now(self) -> None:
        """engine priority-2 用で、予算判定に依らず即スピルする（フック非経由）。"""
        if not self.spilled:
            self._spill_now()

    def _spill_now(self) -> None:
        """メモリ内容を一時ファイルへ退避しスピル状態へ（内部）。"""
        # ファイル名に自 PID＋プロセス開始時刻を埋める（共有 temp での並行 run 識別に使う。
        # cleanup_stale_edge_files が生存中の別 run のファイルを誤削除しないため）。
        # 開始時刻が無いと、死んだ run の残骸は同じ PID が無関係のプロセスに再利用された
        # だけで永久にリークする（PID 再利用の誤保全）。
        fd, p = tempfile.mkstemp(dir=str(self._dir),
                                 prefix=f"ga_edges_{_self_token()}_", suffix=".tsv")
        self._path = Path(p)
        # 内部ストレージは完全往復可逆が要件（読戻して追跡に使う）。SJIS 混在名由来の
        # 孤立サロゲート (U+DC80〜U+DCFF) を strict UTF-8 だと書込で落とすため
        # surrogatepass でロスレス退避する（output_writer の最終出力は replace だが、
        # 内部退避は復元必須なので方針が異なる）。
        self._fh = os.fdopen(fd, "w", encoding="utf-8", errors="surrogatepass")
        for pp, cc in self._mem:
            self._fh.write(serialize_edge(pp, cc) + "\n")
        self._mem = []
        self.spilled = True

    def _write_run(self, edges) -> Path:
        """ソート済みエッジ列を run ファイルへ書き出しパスを返す（外部マージの中間）。"""
        fd, p = tempfile.mkstemp(dir=str(self._dir),
                                 prefix=f"ga_edges_{_self_token()}_run_",
                                 suffix=".tsv")
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogatepass") as w:
            for pp, cc in edges:
                w.write(serialize_edge(pp, cc) + "\n")
        return Path(p)

    @staticmethod
    def _iter_run(path: Path) -> Iterator[tuple[Occurrence, Occurrence]]:
        """run ファイルを 1 行ずつ parse して yield する（遅延読み）。"""
        with open(path, encoding="utf-8", errors="surrogatepass") as r:
            for line in r:
                if line.strip():
                    yield parse_edge(line)

    def sorted_unique(self) -> Iterator[tuple[Occurrence, Occurrence]]:
        """sorted(set(edges)) と同一順序・同一集合を返す（出力透過・決定的）。

        スピル済は全件を set に読み戻さず（スピルの目的が確定段で無効になるため）、
        _SORT_CHUNK_EDGES 件ごとにソート済み run を作り heapq.merge で畳む。
        run 内重複は per-chunk set、run 間重複はマージ列の隣接比較で除く。
        ピークメモリは O(_SORT_CHUNK_EDGES)。
        """
        if not self.spilled:
            yield from sorted(set(self._mem))
            return
        self._fh.flush()
        runs: list[Path] = []
        try:
            chunk: set[tuple[Occurrence, Occurrence]] = set()
            with open(self._path, encoding="utf-8", errors="surrogatepass") as r:  # 書込と対称
                for line in r:
                    if line.strip():
                        chunk.add(parse_edge(line))
                        if len(chunk) >= _SORT_CHUNK_EDGES:
                            runs.append(self._write_run(sorted(chunk)))
                            chunk = set()
            if chunk:
                runs.append(self._write_run(sorted(chunk)))
            prev = None
            for edge in heapq.merge(*(self._iter_run(p) for p in runs)):
                if edge != prev:
                    yield edge
                    prev = edge
        finally:
            for p in runs:
                try:
                    p.unlink()
                except OSError:
                    pass

    def close(self) -> None:
        """一時ファイルを閉じて削除する（確定ループ完了後・例外時も finally で呼ぶ）。

        _fh.close() が失敗（例: クローズ時の flush でディスク満杯）しても一時ファイルの
        unlink は必ず試みる。さもないと自PID保全方針下で残骸が同一プロセス生存中
        回収されずリークする。
        """
        try:
            if self._fh is not None:
                self._fh.close()
        finally:
            self._fh = None
            if self._path is not None and self._path.exists():
                self._path.unlink()
            self._path = None


def _proc_starttime(pid: int) -> str | None:
    """/proc から pid の開始時刻（clock tick）を返す。取得不能（非 Linux 等）は None。

    PID 再利用の識別に使う。値そのものの意味は問わず「同一プロセスなら不変・
    別プロセスなら（ほぼ確実に）異なる」性質だけを利用する。
    """
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            stat_line = f.read()
        # comm はパーレン囲みで空白を含み得るため、閉じパーレン以降を分割する。
        # starttime は comm 以降の第 20 フィールド（man proc: 全体の第 22）。
        return stat_line.rsplit(b")", 1)[1].split()[19].decode("ascii")
    except (OSError, IndexError, UnicodeDecodeError):
        return None


def _self_token() -> str:
    """自プロセスのスピルファイル名トークン `<pid>` または `<pid>-<starttime>` を返す。"""
    pid = os.getpid()
    start = _proc_starttime(pid)
    return f"{pid}-{start}" if start is not None else str(pid)


def _token_from_name(name: str) -> tuple[int, str | None] | None:
    """ga_edges_<pid>[-<start>]_<rand>.tsv から (pid, starttime) を取り出す。

    PID 無しレガシー名は None を返す（stale 扱い）。starttime 無し旧形式は
    (pid, None) を返す。
    """
    rest = name[len("ga_edges_"):]
    head = rest.split("_", 1)[0]
    pid_part, _, start_part = head.partition("-")
    if not pid_part.isdigit():
        return None
    return int(pid_part), (start_part or None)


def _owner_alive(pid: int, start: str | None) -> bool:
    """スピルファイルの所有プロセスが生存中か。

    starttime 付きなら PID 生存に加えて開始時刻の一致も要求し、PID 再利用による
    誤保全（無関係の生存プロセスのせいで残骸が永久リークする）を防ぐ。
    starttime 無し（旧形式・非 Linux）は従来どおり PID 生存のみで判定する。
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass                                  # 他ユーザの生存プロセス＝生存扱い
    if start is not None:
        current = _proc_starttime(pid)
        if current is not None and current != start:
            return False                      # PID 再利用＝所有者は死んでいる
    return True


def cleanup_stale_edge_files(spill_dir: "Path | None" = None) -> int:
    """起動時に残存する ga_edges_* 一時ファイルを掃除する（kill -9 等の遺物）。

    共有 temp ディレクトリでは複数 run が同居し得るため、ファイル名に埋めた PID が
    「生存中のプロセス」のものは（自他を問わず）消さない。これにより並行 run の生存中
    スピルの誤削除を防ぐと同時に、cleanup が（万一）自 run のスピルより後に呼ばれても
    自分のファイルを消して自滅しない（自ファイルの掃除は EdgeStore.close() の責務）。
    死んだ PID・PID 無しレガシー名は stale とみなして掃除する。
    返り値は削除件数である。削除不能（権限・他プロセス使用中）は黙って残す（ベストエフォート）。
    """
    d = Path(spill_dir) if spill_dir is not None else Path(tempfile.gettempdir())
    removed = 0
    try:
        candidates = list(d.glob("ga_edges_*"))
    except OSError:
        return 0
    for p in candidates:
        token = _token_from_name(p.name)
        if token is not None and _owner_alive(*token):
            continue                          # 生存中プロセスのスピル＝保全（自他問わず）
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed
