"""perl/groovy ヒューリスティック snippet 境界（spec §6）。"""

import grep_analyzer.snippet._heuristic as H
from grep_analyzer.snippet import build_snippet


def test_heuristic_spanはファイル全体ではなく窓だけをmaskする(monkeypatch):
    # M1: mask は stop() が触れる窓 [hit±(LINE_MAX-1)] だけに限定すべき。
    # 旧実装はヒットごとに全行を mask し O(ヒット数×ファイルサイズ) になっていた。
    calls = {"n": 0}
    real = H.mask_literals
    monkeypatch.setattr(H, "mask_literals",
                        lambda lang, ln: (calls.__setitem__("n", calls["n"] + 1),
                                          real(lang, ln))[1])
    lines = [f"x{i} = {i};" for i in range(1000)]
    H.heuristic_span(lines, 500, "sql")
    assert calls["n"] <= 2 * H.LINE_MAX            # 全行(1000)を mask しない


def test_perlのsnippetは文末セミコロンで境界を取る():
    # src: 4行。ヒット行2（my $x = 1;）。
    # heuristic_span が動けば return $x; の行も含む複数行 snippet になる。
    # フォールバック (hit,hit) だと1行のみ＝return $x; は入らない。
    src = "sub f {\n    my $x = 1;\n    return $x;\n}\n"
    out = build_snippet("perl", "bourne", src, 2)   # my $x = 1; の行
    assert "my $x = 1;" in out
    # heuristic が機能すれば隣接行も取り込まれる（1行だけなら失敗）
    assert "return $x;" in out


def test_groovyのsnippetは波括弧で境界を取る():
    # src: 5行。ヒット行3（def x = compute()）。
    # heuristic_span が動けば def run() { の行も含む。
    # フォールバック (hit,hit) だと1行のみ＝def run() { は入らない。
    src = "class A {\n    def run() {\n        def x = compute()\n    }\n}\n"
    out = build_snippet("groovy", "bourne", src, 3)
    assert "def x = compute()" in out
    # heuristic が機能すれば上方向の def run() { も取り込まれる
    assert "def run()" in out


def test_perlの大文字SUBは終端と誤判定しない():
    # 小文字 sub のみが Perl の宣言キーワード。大文字 SUB（定数/バレワード）を
    # 終端扱いすると snippet 境界を早期に誤って切る。case-sensitive 化で false-positive を解消。
    lines = ["my $a = 1", "SUB foo bar", "my $b = 2"]
    s, _ = H.heuristic_span(lines, 2, "perl")
    assert s == 0   # SUB 行(index1)で止まらず先頭まで遡る


def test_groovyの大文字DEF_CLASSは終端と誤判定しない():
    lines = ["int a = 1", "DEF foo bar", "int b = 2"]
    s, _ = H.heuristic_span(lines, 2, "groovy")
    assert s == 0
