"""通常ファイル以外（FIFO/デバイス/ソケット）を walk が除外することを検証する（C2）。

FIFO を open().read() するとライタ不在で無限ブロックする。S_ISREG ガードを
open の前に置き、特殊ファイルは診断付きで除外しなければならない。
"""

import os
import threading

import pytest

from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.walk import collect_files_ex


def test_fifoは通常ファイルでないので除外される(tmp_path):
    (tmp_path / "real.txt").write_text("hello\n")
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)

    # 修正前（バグ）は FIFO を open().read() するため、ライタを別スレッドで供給して
    # テスト自体のハングは避ける。修正後はそもそも open しないのでライタは待ち続けるが
    # daemon なのでプロセス終了で回収される。
    def _writer():
        try:
            with open(fifo, "wb") as w:
                w.write(b"x")
        except OSError:
            pass

    t = threading.Thread(target=_writer, daemon=True)
    t.start()

    diag = Diagnostics()
    try:
        files, _total, _unsafe = collect_files_ex(
            tmp_path, include=[], exclude=[], follow_symlinks=False,
            max_file_bytes=1_000_000, diag=diag)
    finally:
        # 修正後はリーダが FIFO を開かないためライタが open(wb) でブロックし続ける。
        # 後続テストの fork 警告を避けるため、読み口を非ブロックで開いて解放し join する。
        try:
            fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
            try:
                os.read(fd, 16)
            finally:
                os.close(fd)
        except OSError:
            pass
        t.join(timeout=5)

    rels = {r for r, _ in files}
    assert "real.txt" in rels
    assert "pipe" not in rels
    assert diag.counts().get("walk_skipped_special", 0) == 1
