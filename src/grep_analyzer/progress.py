"""標準エラー進捗。level=="on" 以外は完全無音。stream（既定 sys.stderr）専用で
TSV/diagnostics/終了コードに無影響。tick は hop 内の途中経過を報告する（liveness 用）。"""

import sys
import time


class Progress:
    """走査進捗を stderr に報告する（level=="on" 以外は完全無音）。"""

    def __init__(self, level: str, stream=None, every: int = 2000) -> None:
        self._on = level == "on"
        self._stream = stream if stream is not None else sys.stderr
        self._total = 0
        self._hop_total = None                # その hop の実走査数（prefilter/chunk 反映）
        self._every = max(1, every)
        self._t0 = None
        self._last = 0

    def _elapsed(self) -> float:
        return time.monotonic() - self._t0 if self._t0 is not None else 0.0

    def start(self, total_files: int) -> None:
        """run 開始を報告し、初回 walk の総ファイル数を既定分母に設定する。"""
        self._total = total_files
        self._t0 = time.monotonic()
        self._last = 0
        if self._on:
            print(f"[grep_analyzer] start files={total_files}",
                  file=self._stream, flush=True)

    def begin_hop(self, hop_total: int) -> None:
        """その hop の実走査数（prefilter 絞り込み・chunk 数を反映）を分母に設定する。

        初回 walk の全ファイル数を分母に使うと、prefilter が効いた hop で
        `scanning 300/50000` のような表示になり「最終件」条件も成立しなくなる。
        """
        self._hop_total = hop_total
        self._last = 0

    def _denominator(self) -> int:
        return self._hop_total if self._hop_total is not None else self._total

    def tick(self, hop: int, scanned: int) -> None:
        """hop 内の途中経過を出す。every 件ごと（と最終件）に出力する。stderr 専用で出力は不変。"""
        if not self._on:
            return
        if scanned - self._last >= self._every or scanned >= self._denominator():
            self._last = scanned
            print(f"[grep_analyzer] hop={hop} scanning {scanned}/{self._denominator()} "
                  f"elapsed={self._elapsed():.0f}s", file=self._stream, flush=True)

    def hop(self, hop: int, n_symbols: int, scanned: int) -> None:
        """hop 完了行を出す（scanned はその hop で実走査したファイル数）。"""
        self._last = 0
        if self._on:
            print(f"[grep_analyzer] hop={hop} done symbols={n_symbols} "
                  f"scanned={scanned}/{self._denominator()} elapsed={self._elapsed():.0f}s",
                  file=self._stream, flush=True)

    def done(self) -> None:
        """run 完了を報告する。"""
        if self._on:
            print(f"[grep_analyzer] done elapsed={self._elapsed():.0f}s",
                  file=self._stream, flush=True)
