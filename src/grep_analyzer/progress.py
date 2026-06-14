"""標準エラー進捗。level=="on" 以外は完全無音。stream（既定 sys.stderr）専用で
TSV/diagnostics/終了コードに無影響。tick は hop 内の途中経過を報告する（liveness 用）。"""

import sys
import time


class Progress:
    def __init__(self, level: str, stream=None, every: int = 2000) -> None:
        self._on = level == "on"
        self._stream = stream if stream is not None else sys.stderr
        self._total = 0
        self._every = max(1, every)
        self._t0 = None
        self._last = 0

    def _elapsed(self) -> float:
        return time.monotonic() - self._t0 if self._t0 is not None else 0.0

    def start(self, total_files: int) -> None:
        self._total = total_files
        self._t0 = time.monotonic()
        self._last = 0
        if self._on:
            print(f"[grep_analyzer] start files={total_files}",
                  file=self._stream, flush=True)

    def tick(self, hop: int, scanned: int) -> None:
        """hop 内の途中経過を出す。every 件ごと（と最終件）に出力する。stderr 専用で出力は不変。"""
        if not self._on:
            return
        if scanned - self._last >= self._every or scanned >= self._total:
            self._last = scanned
            print(f"[grep_analyzer] hop={hop} scanning {scanned}/{self._total} "
                  f"elapsed={self._elapsed():.0f}s", file=self._stream, flush=True)

    def hop(self, hop: int, n_symbols: int, scanned: int) -> None:
        self._last = 0
        if self._on:
            print(f"[grep_analyzer] hop={hop} done symbols={n_symbols} "
                  f"scanned={scanned}/{self._total} elapsed={self._elapsed():.0f}s",
                  file=self._stream, flush=True)

    def done(self) -> None:
        if self._on:
            print(f"[grep_analyzer] done elapsed={self._elapsed():.0f}s",
                  file=self._stream, flush=True)
