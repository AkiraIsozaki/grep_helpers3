"""静的シンボル採否ポリシーの仕様（spec §8.3・cap は大域で fixedpoint 側）。"""

from grep_analyzer.model import ChaseSymbols
from grep_analyzer.stoplist import LANG_KEYWORDS, SymbolPolicy, admit, load_stoplist, partition


def _pol(min_spec=2, stop=frozenset()):
    return SymbolPolicy(min_specificity=min_spec, user_stoplist=stop)


def test_言語キーワードは採用しない():
    r = admit(["if", "STATUS_OK", "class"], "java", _pol())
    assert r.accepted == ["STATUS_OK"]
    assert ("if", "keyword") in r.rejected and ("class", "keyword") in r.rejected


def test_最小長未満は採用しない():
    r = admit(["x", "ab", "abc"], "c", _pol(min_spec=3))
    assert r.accepted == ["abc"]
    assert ("x", "too_short") in r.rejected and ("ab", "too_short") in r.rejected


def test_ユーザストップリストは採用しない():
    r = admit(["FOO", "BAR"], "c", _pol(stop=frozenset({"BAR"})))
    assert r.accepted == ["FOO"] and ("BAR", "user_stoplist") in r.rejected


def test_順序保存で採否しcapはここで行わない():
    r = admit(["zzz", "ab", "yy"], "c", _pol(min_spec=1))
    assert r.accepted == ["zzz", "ab", "yy"]


def test_ストップリストファイルは空行とコメントを無視する(tmp_path):
    f = tmp_path / "stop.txt"
    f.write_text("# c\nFOO\n\n  BAR  \n", "utf-8")
    assert load_stoplist(f) == frozenset({"FOO", "BAR"})
    assert load_stoplist(None) == frozenset()


def test_getterとsetterは横展開せずterminalへ回す():
    cs = ChaseSymbols(constants=("STATUS_OK",), vars=("count",), getters=("getName",), setters=("setX",))
    p = partition(cs, "java", _pol(min_spec=2))
    assert p.chase == ["STATUS_OK", "count"]
    assert p.terminal == ["getName", "setX"] and p.rejected == []


def test_terminalにもキーワード最小長は効く():
    cs = ChaseSymbols(getters=("getX",), setters=("set",))
    p = partition(cs, "java", _pol(min_spec=4))
    assert p.terminal == ["getX"] and ("set", "too_short") in p.rejected


def test_perl予約語は追跡集合に入らない():
    pol = SymbolPolicy(min_specificity=2, user_stoplist=frozenset())
    r = admit(["print", "my", "sub", "if", "while", "userCode"], "perl", pol)
    assert r.accepted == ["userCode"]
    assert {s for s, _ in r.rejected} == {"print", "my", "sub", "if", "while"}


def test_groovy予約語は追跡集合に入らない():
    pol = SymbolPolicy(min_specificity=2, user_stoplist=frozenset())
    r = admit(["def", "class", "while", "return", "println", "orderId"], "groovy", pol)
    assert r.accepted == ["orderId"]
    assert {s for s, _ in r.rejected} == {"def", "class", "while", "return", "println"}


def test_sqlのOracleデータ型は追跡集合に入らない():
    # PL/SQL 慣例の大文字形で登録するため大文字で棄却を要求する（admit は case-sensitive）
    pol = SymbolPolicy(min_specificity=2, user_stoplist=frozenset())
    r = admit(["NUMBER", "VARCHAR2", "BOOLEAN", "v_code"], "sql", pol)
    assert r.accepted == ["v_code"]


def test_新言語の予約語がLANG_KEYWORDSに登録される():
    from grep_analyzer.stoplist import LANG_KEYWORDS
    for lang in ("python", "javascript", "typescript", "tsx"):
        assert lang in LANG_KEYWORDS
    assert "class" in LANG_KEYWORDS["python"]
    assert "const" in LANG_KEYWORDS["javascript"]
    assert "interface" in LANG_KEYWORDS["typescript"]


def test_予約語はadmitで棄却される():
    from grep_analyzer.stoplist import admit, SymbolPolicy
    pol = SymbolPolicy(min_specificity=2, user_stoplist=frozenset())
    res = admit(["const", "myVar"], "javascript", pol)
    assert res.accepted == ["myVar"]
    assert ("const", "keyword") in res.rejected


def test_jsp_html_keyword_登録():
    assert "page" in LANG_KEYWORDS["jsp"] and "class" in LANG_KEYWORDS["jsp"]
    assert LANG_KEYWORDS["html"] == frozenset()


def test_1文字記号はmin_specificity2でtoo_short棄却():
    """B7a: min_specificity=2 のとき 1 文字記号は too_short で棄却・2 文字は accepted（健全確認）。

    `stoplist.py:104` の `len(s) < policy.min_specificity` ガードが意図どおり機能する。
    """
    pol = SymbolPolicy(min_specificity=2, user_stoplist=frozenset())
    r = admit(["T", "ab"], "java", pol)
    assert ("T", "too_short") in r.rejected, "1文字 T は too_short で棄却"
    assert "ab" in r.accepted, "2文字 ab は accepted"


def test_小文字SQL型名のすり抜け():
    """B7c: admit は case-sensitive のため小文字 number は accepted（健全・二次防御の意図どおり）。

    _SQL_KW は PL/SQL 慣例の大文字形 NUMBER 等で登録されており admit は case-sensitive 完全一致。
    小文字 number は SQL キーワード集合に含まれないためすり抜けて accepted になる。
    これは意図的な設計（型名除外は二次防御で主防御は AST/分類側）。
    """
    pol = SymbolPolicy(min_specificity=2, user_stoplist=frozenset())
    # 大文字 NUMBER は keyword 棄却（登録済み）
    assert ("NUMBER", "keyword") in admit(["NUMBER"], "sql", pol).rejected
    # 小文字 number は accepted（すり抜け）= case-sensitive 設計の意図どおり
    r = admit(["number"], "sql", pol)
    assert "number" in r.accepted, "B7c: 小文字 number は大文字 NUMBER と別扱い（case-sensitive）"
