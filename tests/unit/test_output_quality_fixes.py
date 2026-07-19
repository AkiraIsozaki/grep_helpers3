"""出力品質の是正仕様（encoding 正規化・name 行ゲート・SQL 大小無別・分類規則・span）。

いずれも「同一コーパス内での表記の割れ」「偽シンボル混入」「取りこぼし」を塞ぐもの。
"""
import pytest

from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes


class TestEncoding正規化:
    def test_chardetのSHIFT_JIS検出はcp932へ正規化する(self, monkeypatch):
        # Python の shift_jis codec は cp932 と写像が異なる（0x8160: U+301C vs U+FF5E）。
        # 同一コーパス内で拡張文字の有無により正規化が割れるため cp932 へ寄せる。
        monkeypatch.setattr(
            "grep_analyzer.encoding.chardet.detect",
            lambda b: {"encoding": "SHIFT_JIS", "confidence": 0.99})
        data = "テスト～".encode("cp932")          # 0x8160 波ダッシュ問題の当事者
        text, enc, replaced = decode_bytes(data, DEFAULT_FALLBACK)
        assert enc == "cp932"
        assert text == "テスト～"                  # cp932 写像（U+FF5E）で復号される
        assert replaced is False

    def test_1バイト系誤検出はfallback鎖の多バイトstrict成功を優先する(self, monkeypatch):
        # 1 バイト系 codec はほぼ全バイト列で strict 成功するため、chardet の誤検出が
        # 「要確認」なしの silent mojibake になる。cp932/euc-jp の strict 成功を優先する。
        monkeypatch.setattr(
            "grep_analyzer.encoding.chardet.detect",
            lambda b: {"encoding": "Windows-1252", "confidence": 0.7})
        data = "あいうえお日本語".encode("cp932")
        text, enc, replaced = decode_bytes(data, DEFAULT_FALLBACK)
        assert enc == "cp932"
        assert text == "あいうえお日本語"

    def test_1バイト系検出でも多バイトfallbackが全滅なら検出結果を使う(self, monkeypatch):
        monkeypatch.setattr(
            "grep_analyzer.encoding.chardet.detect",
            lambda b: {"encoding": "Windows-1252", "confidence": 0.9})
        data = b"caf\xe9"                          # cp932/euc-jp では不正、cp1252 では é
        text, enc, replaced = decode_bytes(data, DEFAULT_FALLBACK)
        assert enc == "windows-1252"
        assert text == "café"


class TestName行ゲート:
    def _extract(self, language, src, lineno):
        from grep_analyzer.chase import extract_chase_symbols_tree
        return extract_chase_symbols_tree(language, src, lineno)

    def test_python_propertyの本体行ヒットはgetterを放出しない(self):
        src = ("class A:\n"
               "    @property\n"
               "    def name(self):\n"
               "        x = compute()\n"
               "        return x\n")
        body = self._extract("python", src, 4)
        assert body.getters == ()                  # 偽 getter 混入の抑止
        assert body.vars == ("x",)
        assert self._extract("python", src, 5).getters == ()
        assert self._extract("python", src, 3).getters == ("name",)  # name 行は従来どおり

    def test_js_getterの本体行ヒットはgetterを放出しない(self):
        src = ("class A {\n"
               "  get name() {\n"
               "    const x = 1;\n"
               "    return x;\n"
               "  }\n"
               "}\n")
        assert self._extract("javascript", src, 3).getters == ()
        assert self._extract("javascript", src, 5).getters == ()     # `}` のみの行
        assert self._extract("javascript", src, 2).getters == ("name",)

    def test_ts_enumはヒット行のmemberのみを放出する(self):
        src = "enum Color {\n  Red,\n  Green = 2,\n}\n"
        assert self._extract("typescript", src, 2).constants == ("Red",)
        assert self._extract("typescript", src, 3).constants == ("Green",)

    def test_js_for_ofのループ変数を抽出する(self):
        src = "for (const item of items) {\n  use(item);\n}\n"
        assert "item" in (self._extract("javascript", src, 1).constants
                          + self._extract("javascript", src, 1).vars)


class TestSQL大小無別:
    def test_scan_lineはSQLで大小無別に照合し原綴りを返す(self):
        from grep_analyzer.automaton import build_pair, scan_line_for_language
        pair = build_pair(["V_CNT"])
        assert scan_line_for_language(pair, "v_cnt := v_cnt + 1;", "sql") == ["V_CNT"]
        assert scan_line_for_language(pair, "V_CNT := 1;", "sql") == ["V_CNT"]
        # SQL 以外は従来どおり case-sensitive
        assert scan_line_for_language(pair, "v_cnt := 1;", "java") == []

    def test_scan_line_ciも語境界を判定する(self):
        from grep_analyzer.automaton import build_pair, scan_line_for_language
        pair = build_pair(["CNT"])
        assert scan_line_for_language(pair, "v_cnt := 1;", "sql") == []   # 部分文字列は不採用

    def test_admitはSQLキーワードを大小無別に棄却する(self):
        from grep_analyzer.stoplist import SymbolPolicy, admit
        policy = SymbolPolicy(2, frozenset())
        res = admit(["WHERE", "number", "V_CNT"], "sql", policy)
        assert res.accepted == ["V_CNT"]
        assert [s for s, _ in res.rejected] == ["WHERE", "number"]


class Test分類規則:
    def test_sql複数行ブロックコメント内部はコメント扱い(self):
        from grep_analyzer.classify import classify_hit
        text = "/* UPDATE 2020-01: fixed\n * INSERT was slow */\nSELECT 1;\n"
        assert classify_hit("sql", None, text, 1, "/* UPDATE 2020-01: fixed")[0] == "コメント"
        assert classify_hit("sql", None, text, 2, " * INSERT was slow */")[0] == "コメント"
        assert classify_hit("sql", None, text, 3, "SELECT 1;")[0] != "コメント"

    def test_sqlヒント句はコメント扱いしない(self):
        from grep_analyzer.classify import classify_hit
        text = "/*+ INDEX(t idx) */\nUPDATE t SET a=1;\n"
        assert classify_hit("sql", None, text, 1, "/*+ INDEX(t idx) */")[0] != "コメント"

    def test_groovy複数行ブロックコメント内部はコメント扱い(self):
        from grep_analyzer.classify import classify_hit
        text = "/* count = legacy behaviour\n * retry if broken */\ndef x = 1\n"
        assert classify_hit("groovy", None, text, 1,
                            "/* count = legacy behaviour")[0] == "コメント"
        assert classify_hit("groovy", None, text, 2,
                            " * retry if broken */")[0] == "コメント"

    def test_java_whileとforは分岐に分類する(self):
        from grep_analyzer.classify import classify_hit
        text = ("class A {\n void f() {\n  while (cnt == 1) { y(); }\n"
                "  for (int i = 0; i < n; i++) { y(); }\n }\n}\n")
        assert classify_hit("java", None, text, 3,
                            "  while (cnt == 1) { y(); }") == ("分岐", "high")
        assert classify_hit("java", None, text, 4,
                            "  for (int i = 0; i < n; i++) { y(); }") == ("分岐", "high")

    def test_shellのexport付き代入は代入に分類する(self):
        from grep_analyzer.classifiers.regex_classifier import classify_shell
        assert classify_shell("export PATH=/usr/bin")[0] == "代入"
        assert classify_shell("local count=1")[0] == "代入"

    def test_perlのダイヤモンド演算子は比較にしない(self):
        from grep_analyzer.classifiers.regex_classifier import classify_perl
        assert classify_perl("while (<STDIN>) {")[0] == "分岐"

    def test_groovyジェネリクス付きメソッド宣言は宣言に分類する(self):
        from grep_analyzer.classifiers.regex_classifier import classify_groovy
        assert classify_groovy("List<String> getNames() {")[0] == "宣言"
        assert classify_groovy("return foo(1)")[0] != "宣言"     # 過剰一致の抑止


class TestTSV無害化:
    def test_先頭二重引用符は無害化される(self):
        # Excel は .tsv 直開きで先頭 `"` をテキスト修飾子として扱い、閉じ `"` まで
        # 後続セルを併合する。数式トリガと同様に `'` 前置で無害化する。
        from grep_analyzer.tsv import neutralize_formula
        assert neutralize_formula('"MS932" をサポート') == '\'"MS932" をサポート'
        assert neutralize_formula("plain") == "plain"


class TestSpan修正:
    def test_jsp_region_spanはディレクティブをcode区間と誤認しない(self):
        from grep_analyzer.embed_preprocess import jsp_region_span
        assert jsp_region_span("<%@ page contentType=\"text/html\" %>\n", 1) is None
        assert jsp_region_span("<%-- comment\n more --%>\n", 1) is None
        assert jsp_region_span("<% int x = 1; %>\n", 1) == (0, 0)

    def test_proc終端セミコロン欠落は空行で巻き込みを止める(self):
        from grep_analyzer.proc_preprocess import exec_spans
        src = "EXEC SQL WHENEVER SQLERROR CONTINUE\n\nint y = 2;\n"
        spans = exec_spans(src)
        assert spans and spans[0][1] <= 1          # 空行まで（int y の行は含めない）

    def test_proc終端欠落でも次のEXECで巻き込みを止める(self):
        from grep_analyzer.proc_preprocess import mask_exec_sql
        src = "EXEC SQL WHENEVER SQLERROR CONTINUE\nEXEC SQL COMMIT;\nint z = 3;\n"
        masked = mask_exec_sql(src)
        assert "int z = 3;" in masked

    def test_shellの配列長展開はコメント扱いしない(self):
        from grep_analyzer.patterns.literal_masking import mask_literals
        masked = mask_literals("shell", "echo ${#arr[@]} more")
        assert "${#arr[@]}" in masked              # $ { # を潰さない
        assert mask_literals("shell", "echo x # comment") == "echo x          "

    def test_heuristic_spanの上方向は前文の終端行を含めない(self):
        from grep_analyzer.snippet._heuristic import heuristic_span
        lines = ["UPDATE t SET a=1;", "SELECT x", "FROM t;"]
        span = heuristic_span(lines, 1, "sql")
        assert span[0] == 1                        # 前文の `;` 行は含めない
        assert span[1] == 2
