"""tree-sitter 分類（spec §7）。構文位置が確定すれば high。"""

from grep_analyzer.classifiers.ts_classifier import classify_ts


def test_Javaのif比較行は比較highと判定する():
    src = 'class A {\n void m(){\n  if (s.equals("K")) {}\n }\n}\n'
    assert classify_ts("java", src, 3) == ("比較", "high")


def test_Javaのフィールド宣言は宣言highと判定する():
    src = 'class A {\n static final String K = "K";\n}\n'
    assert classify_ts("java", src, 2) == ("宣言", "high")


def test_Cのdefineは宣言highと判定する():
    src = '#define CODE "X"\nint main(){return 0;}\n'
    assert classify_ts("c", src, 1) == ("宣言", "high")


def test_ProCはEXEC_SQLをマスクしてもC宣言を分類できる():
    # `char *p = "X";` は C の declaration（宣言）。EXEC SQL 行が中立化されても
    # 行番号保存のため3行目が宣言として解釈できることを確認する。
    src = 'int f(){\n EXEC SQL SELECT 1;\n char *p = "X";\n}\n'
    assert classify_ts("proc", src, 3) == ("宣言", "high")


def test_python_category():
    assert classify_ts("python", "X = 1\n", 1) == ("代入", "high")
    assert classify_ts("python", "if a == b:\n    pass\n", 1) == ("比較", "high")
    assert classify_ts("python", "from x import y\n", 1) == ("宣言", "high")
    assert classify_ts("python", "def f():\n    return z\n", 2) == ("return", "high")


def test_javascript_category():
    assert classify_ts("javascript", "const X = 1;\n", 1) == ("宣言", "high")
    assert classify_ts("javascript", "a = b;\n", 1) == ("代入", "high")
    assert classify_ts("javascript", "switch (x) { case 1: break; }\n", 1) == ("分岐", "high")


def test_typescript_category():
    assert classify_ts("typescript", "enum E { A, B }\n", 1) == ("宣言", "high")
    assert classify_ts("typescript", "interface I { x: number; }\n", 1) == ("宣言", "high")


def test_tsx_category():
    assert classify_ts("tsx", "const App = () => <div>{x}</div>;\n", 1) == ("宣言", "high")


def test_bindings_at_line_行交差全件を決定的順で返す():
    from grep_analyzer.classifiers.ast_base import bindings_at_line, parse_tree
    root = parse_tree("java", "class S { int vv = a.getName(); }\n")
    types = {"field_declaration", "method_invocation"}
    got = [n.type for n in bindings_at_line(root, 1, types)]
    # field_declaration（外側・start_byte 小）→ method_invocation（内側）の順
    assert got == ["field_declaration", "method_invocation"]


def test_bindings_at_line_該当なしは空list():
    from grep_analyzer.classifiers.ast_base import bindings_at_line, parse_tree
    root = parse_tree("java", "class S {}\n")
    assert bindings_at_line(root, 1, {"method_invocation"}) == []


def test_コメント行はコメントlowと判定する_各AST言語():
    assert classify_ts("java", "class A {\n // 777\n}\n", 2) == ("コメント", "low")
    assert classify_ts("java", "class A {\n /* 777 */\n}\n", 2) == ("コメント", "low")
    assert classify_ts("c", "int x;\n// 777\n", 2) == ("コメント", "low")
    assert classify_ts("c", "int x;\n/* 777 */\n", 2) == ("コメント", "low")
    assert classify_ts("python", "# 777\nx = 1\n", 1) == ("コメント", "low")
    assert classify_ts("javascript", "// 777\nconst x = 1;\n", 1) == ("コメント", "low")
    assert classify_ts("typescript", "// 777\nconst x = 1;\n", 1) == ("コメント", "low")


def test_文ブロック内ネストコメントもコメントになる():
    src = "class A {\n void m(int x){\n  if (x == 1) {\n   // 777\n  }\n }\n}\n"
    assert classify_ts("java", src, 4) == ("コメント", "low")


def test_コード同居行はコメントにせずコード分類():
    assert classify_ts("java", 'class A {\n int x = 1; // 777\n}\n', 2) == ("宣言", "high")


def test_巨大ソースはparseを諦めその他lowへ決定的降格(monkeypatch):
    # 60GB 想定で --max-file-bytes を上げた際の巨大 minified 1 ファイルで worker OOM を防ぐ。
    # 上限超は _ParseFailed→("その他","low") に決定的降格する（#K）。
    from grep_analyzer.classifiers import ast_base, ts_classifier
    monkeypatch.setattr(ast_base, "_MAX_PARSE_BYTES", 100)
    big = "class A { int x = 1; }\n" + "// pad " * 50    # >100 bytes
    assert len(big.encode("utf-8")) > 100
    assert ts_classifier.classify_ts("java", big, 1) == ("その他", "low")


def test_上限以内のソースは通常どおりAST分類される(monkeypatch):
    from grep_analyzer.classifiers import ast_base, ts_classifier
    monkeypatch.setattr(ast_base, "_MAX_PARSE_BYTES", 10_000)
    cat, conf = ts_classifier.classify_ts("java", "class A { int x = 1; }\n", 1)
    assert conf == "high"
