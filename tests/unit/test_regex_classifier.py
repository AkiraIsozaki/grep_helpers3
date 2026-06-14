"""SQL/Shell の正規表現分類（spec §7）。confidence は medium。"""

from grep_analyzer.classifiers.regex_classifier import classify_sql, classify_shell


def test_SQLのWHERE比較は比較と判定する():
    assert classify_sql("WHERE col = 'X'") == ("比較", "medium")


def test_SQLのINSERT_VALUESは代入と判定する():
    assert classify_sql("INSERT INTO t VALUES ('X')") == ("代入", "medium")


def test_Shellの変数代入は代入と判定する():
    assert classify_shell('CODE="X"') == ("代入", "medium")


def test_Shellのtest比較は比較と判定する():
    assert classify_shell('[ "$x" = "X" ]') == ("比較", "medium")


def test_該当規則がなければその他と判定する():
    assert classify_sql("SELECT 1 FROM dual") == ("その他", "medium")


def test_OracleのPLSQL代入は代入と判定する():
    assert classify_sql("v_code := 'X';") == ("代入", "medium")


def test_OracleのDECODEは分岐と判定する():
    assert classify_sql("SELECT DECODE(st,1,'OK','NG') FROM dual") == ("分岐", "medium")


def test_OracleのCASE_WHENは分岐と判定する():
    assert classify_sql("SELECT CASE WHEN st=1 THEN 'A' END FROM dual") == ("分岐", "medium")


def test_既存のWHERE比較とINSERT代入はOracle規則でも不変():
    assert classify_sql("WHERE col = 'X'") == ("比較", "medium")
    assert classify_sql("INSERT INTO t VALUES ('X')") == ("代入", "medium")


def test_cshellのset代入は代入と判定する():
    assert classify_shell("set CODE = \"X\"", "cshell") == ("代入", "medium")
    assert classify_shell("setenv PATH /usr/bin", "cshell") == ("代入", "medium")
    assert classify_shell("@ i = 1", "cshell") == ("代入", "medium")


def test_cshellのif括弧比較は比較と判定する():
    assert classify_shell('if ( "$x" == "X" ) then', "cshell") == ("比較", "medium")


def test_cshellのswitchは分岐と判定する():
    assert classify_shell("switch ( $x )", "cshell") == ("分岐", "medium")


def test_dialect既定bourneは従来挙動と同一():
    assert classify_shell('CODE="X"') == ("代入", "medium")
    assert classify_shell('[ "$x" = "X" ]') == ("比較", "medium")


def test_SQLのコメント行はコメントlow():
    assert classify_sql("-- comment 777") == ("コメント", "low")
    assert classify_sql("  -- indented") == ("コメント", "low")
    assert classify_sql("/* block 777 */") == ("コメント", "low")


def test_SQLのOracleヒント句はコメントにしない():
    assert classify_sql("/*+ INDEX(t idx) */") == ("その他", "medium")
    assert classify_sql("--+ INDEX(t idx)") == ("その他", "medium")


def test_SQLの同居コメントはコード優先():
    assert classify_sql("WHERE col = 'X' -- trailing") == ("比較", "medium")


def test_Shellのコメント行はコメントlow():
    assert classify_shell("# comment 777") == ("コメント", "low")
    assert classify_shell("  # indented") == ("コメント", "low")
    assert classify_shell("# cshell comment", "cshell") == ("コメント", "low")


import time

from grep_analyzer.classifiers.regex_classifier import classify_groovy
from grep_analyzer.chase import extract_chase_symbols


def test_groovy_classifyは長行でもReDoSしない():
    # 閾値 2.0s は catastrophic backtracking（旧実装は数十秒〜）を検知しつつ
    # cold-start/JIT/負荷揺れ（0.3〜0.4s 観測）での偶発 FAIL を避ける（test_chase.py と同基準）。
    for adv in (" " * 100000 + "x = 1", "public " + "static " * 20000 + "x"):
        t0 = time.perf_counter()
        classify_groovy(adv)
        assert time.perf_counter() - t0 < 2.0


def test_groovy_chaseは長行でもReDoSしない():
    for adv in ("final " + " " * 100000, "public " + "static " * 20000 + "x"):
        t0 = time.perf_counter()
        extract_chase_symbols("groovy", "bourne", adv)
        assert time.perf_counter() - t0 < 2.0


def test_groovy_クランプ閾値内の分類_抽出は不変():
    assert classify_groovy("public static final int MAX = 1") == ("代入", "medium")
    cs = extract_chase_symbols("groovy", "bourne", "public static final int MAX = 1")
    assert "MAX" in cs.constants


# --- B5: SQL/Shell リテラルマスク ---


def test_sql文字列内WHEREは比較にしない():
    # B5: 文字列内の WHERE を誤って「比較」にしない。
    # ※ := を含まない行を使う（:= があると _SQL_RULES 先頭の代入が先勝ちし
    #   WHERE 判定に到達しないため、mask の有無で結果が変わらず再現にならない）。
    # 現状(mask 未適用): 文字列内 WHERE...= が \bWHERE\b.*?[=<>] にマッチし「比較」になる。
    assert classify_sql("raise_msg('found WHERE a=b')")[0] != "比較"
    # コード上の WHERE は比較を維持
    assert classify_sql("DELETE FROM t WHERE id = 1")[0] == "比較"


def test_shell文字列内比較は誤分類しない():
    # コード上の [ x = y ] は比較を維持（mask 後も = はリテラル外に残る）
    assert classify_shell('[ "$x" = "y" ]', "bourne")[0] == "比較"
