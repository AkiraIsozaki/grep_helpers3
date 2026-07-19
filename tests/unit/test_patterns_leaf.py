"""patterns/ 葉モジュールと行ベース chaser（sql/shell/groovy）の直接仕様。

呼び出し元（chase facade）経由でしか検証されていなかった境界仕様を、
モジュール自身の縄張りとして固定する（unit＝個々の関数の細かい仕様）。
"""
from grep_analyzer.chase import extract_chase_symbols
from grep_analyzer.patterns.symbol_extraction import (
    BOURNE_ASSIGN_RE,
    ORACLE_CONSTANT_RE,
    ORACLE_DECL_ASSIGN_RE,
)


class TestSymbolExtraction:
    def test_bourne代入は接頭辞とオプションを許容する(self):
        assert BOURNE_ASSIGN_RE.match("export PATH=/bin").group(1) == "PATH"
        assert BOURNE_ASSIGN_RE.match("declare -r X=1").group(1) == "X"
        assert BOURNE_ASSIGN_RE.match("local n=0").group(1) == "n"
        assert BOURNE_ASSIGN_RE.match("A==B") is None      # == は比較

    def test_oracle宣言代入は型トークン付きでも名前を採る(self):
        assert ORACLE_DECL_ASSIGN_RE.search("v_x NUMBER := 0").group(1) == "v_x"
        assert ORACLE_DECL_ASSIGN_RE.search("v_y := 1").group(1) == "v_y"
        assert ORACLE_DECL_ASSIGN_RE.search("c CONSTANT NUMBER := 9").group(1) == "c"
        # 大小無別（IGNORECASE）: 小文字 constant でも同様
        assert ORACLE_CONSTANT_RE.search("rate constant NUMBER").group(1) == "rate"


class TestLineChasers:
    def test_sql_chaserは代入左辺を抽出する(self):
        cs = extract_chase_symbols("sql", None, "v_cnt := v_cnt + 1;")
        assert "v_cnt" in cs.vars

    def test_shell_chaserはexport付き代入の変数を抽出する(self):
        cs = extract_chase_symbols("shell", "bourne", "export RETRY_MAX=3")
        assert "RETRY_MAX" in cs.vars

    def test_groovy_chaserは代入左辺を抽出しコメントは抽出しない(self):
        cs = extract_chase_symbols("groovy", None, "def retryCount = 3")
        assert "retryCount" in cs.vars
        empty = extract_chase_symbols("groovy", None, "// retryCount = 3")
        assert empty.vars == () and empty.constants == ()


class TestLeafImportGuard:
    def test_patternsはgrep_analyzer内を一切importしない_葉性の機械強制(self):
        # 層分離規約（patterns/* は何にも依存しない葉）の番兵。回帰したらここで落ちる。
        import ast
        import grep_analyzer.patterns as patterns_pkg
        from pathlib import Path as _P
        pkg_dir = _P(patterns_pkg.__file__).parent
        offenders = []
        for py in sorted(pkg_dir.glob("*.py")):
            tree = ast.parse(py.read_text("utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for name in names:
                    if name.startswith("grep_analyzer"):
                        offenders.append(f"{py.name}: {name}")
        assert offenders == [], offenders
