"""標準エラー進捗の仕様（spec §8.2・stderr 専用・off 無音）。"""

import io

from grep_analyzer.progress import Progress


def test_offは完全無音():
    buf = io.StringIO()
    p = Progress("off", buf)
    p.start(10); p.hop(1, 5, 3); p.done()
    assert buf.getvalue() == ""


def test_onは各局面でstderrへ構造化出力():
    buf = io.StringIO()
    p = Progress("on", buf)
    p.start(2); p.hop(1, 4, 2); p.done()
    o = buf.getvalue()
    assert "files=2" in o and "hop=1" in o and "symbols=4" in o
    assert "scanned=2" in o and "done" in o


def test_未知levelはoff扱いで無音():
    buf = io.StringIO()
    Progress("verbose-unknown", buf).hop(1, 1, 1)
    assert buf.getvalue() == ""


def test_tickはeveryごとに走査途中の件数をstderrへ出す():
    buf = io.StringIO()
    p = Progress("on", stream=buf, every=3)
    p.start(10)
    for i in range(1, 8):
        p.tick(hop=1, scanned=i)
    out = buf.getvalue()
    assert out.count("scanning") >= 2
    assert "1/10" not in out


def test_progressがoffならtickは無音():
    buf = io.StringIO()
    p = Progress("off", stream=buf, every=1)
    p.start(10)
    p.tick(hop=1, scanned=5)
    assert buf.getvalue() == ""
