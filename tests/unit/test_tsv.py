"""TSV サニタイズ規約のユニットテスト（spec §9 規約①）。"""

from grep_analyzer.tsv import sanitize_field


def test_拡張空白文字を半角空白へ():
    assert sanitize_field("a\tb\rc\nd\x0be\x0cf\x85g h i") == \
        "a b c d e f g h i"


def test_U2028_U2029も空白化_spec11名指し集合():
    assert sanitize_field("a b c") == "a b c"


def test_通常文字とU2026マーカは保持():
    assert sanitize_field("…(+3上行省略) X") == "…(+3上行省略) X"


def test_全制御文字を空白化_C0_DEL_C1():
    # NUL/C0制御/DEL(U+007F)/C1(U+0080-009F) はすべて半角空白へ
    src = "a\x00b\x01c\x1fd\x7fe\x80f\x9fg"
    assert sanitize_field(src) == "a b c d e f g"


def test_旧空白集合と新規制御文字の混在も空白化():
    # 後方互換: 旧集合(\t\n U+0085)と新規(NUL/DEL/C1)が混在しても全て空白へ
    assert sanitize_field("a\tb\nc\x85d\x00e\x7ff\x9fg") == "a b c d e f g"


def test_数式トリガ先頭セルをクオート前置で無害化():
    # Excel/LibreOffice は = + - @ 始まりのセルを数式評価する（CSV/TSV injection）。
    # 出力は BOM 付き Excel 互換なので untrusted ソース由来セルを無害化する。
    from grep_analyzer.tsv import neutralize_formula
    assert neutralize_formula("=cmd|'/c calc'!A1") == "'=cmd|'/c calc'!A1"
    assert neutralize_formula("@Override foo") == "'@Override foo"
    assert neutralize_formula("-1+2") == "'-1+2"
    assert neutralize_formula("+x") == "'+x"
    assert neutralize_formula("normal text") == "normal text"
    assert neutralize_formula("") == ""


def test_data_lineは各セルに数式ガードを適用():
    # 書込側と data_sha 側が共有する _data_line で無害化されることを固定。
    from grep_analyzer.output_writer import _data_line
    from grep_analyzer.model import Hit
    h = Hit(keyword="kw", language="java", file="/abs/A.java", lineno=1,
            ref_kind="direct", category="c", category_sub="", usage_summary="u",
            via_symbol="", chain="kw@A.java:1", snippet="@Override x()",
            encoding="utf-8", confidence="high")
    cells = _data_line(h).split("\t")
    assert "'@Override x()" in cells           # snippet 列が無害化される
