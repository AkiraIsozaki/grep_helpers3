"""言語別シンボル抽出 regex。

マスク後の行から代入左辺・const 定義等を切り出すために使う。

- SQL (Oracle/PL-SQL): `name [CONSTANT] [TYPE] := …` の先頭 id。CONSTANT は定数。バインド `:v`／置換 `&v` は除外
- Shell (bourne): 行頭 `var=` の左辺
- Shell (cshell): `set v =` / `setenv V` / `@ v =` の左辺
注: Java/C は AST 経路のため regex 非対象。
"""

import re

# PL/SQL := 抽出。名前と := の間に型トークンがあれば宣言形＝先頭 id を採り型名を捨てる。
# 型トークン無しは通常代入＝その id。IGNORECASE 必須（小文字 constant のリーク防止）。
ORACLE_DECL_ASSIGN_RE = re.compile(
    r"(?<![:&])\b([A-Za-z_]\w*)(?:\s+(?:CONSTANT\s+)?[A-Za-z_][\w%.]*(?:\([^)]*\))?)?\s*:=",
    re.IGNORECASE)
ORACLE_CONSTANT_RE = re.compile(r"(?<![:&])\b([A-Za-z_]\w*)\s+CONSTANT\b", re.IGNORECASE)

# 宣言子接頭辞（export/local/declare/typeset・フラグ可）を任意で許容し左辺 id を採る。
# readonly は BOURNE_READONLY_RE（constant 経路）に委譲するため含めない。
# `=(?!=)` で比較 == を除外。
BOURNE_ASSIGN_RE = re.compile(
    r"^\s*(?:(?:export|local|declare|typeset)\s+(?:-\w+\s+)*)?([A-Za-z_]\w*)=(?!=)")

CSHELL_ASSIGN_RE = re.compile(
    r"^\s*(?:set\s+([A-Za-z_]\w*)\s*=|setenv\s+([A-Za-z_]\w*)\b|@\s+([A-Za-z_]\w*)\s*=)"
)

BOURNE_READONLY_RE = re.compile(r"^\s*readonly\s+([A-Za-z_]\w*)=")

# Perl: sigil 付き代入左辺（== / =~ / => は除外）。sigil を剥がして bare 識別子を採る。
PERL_ASSIGN_RE = re.compile(r"[$@%](\w+)\s*=(?![=~>])")
PERL_USE_CONSTANT_RE = re.compile(r"\buse\s+constant\s+(\w+)")

# GROOVY 正規表現（CONST/VAR）はカタストロフィックバックトラッキングを起こすため、
# 入力行をこの文字数で頭打ちにして最悪時間を有界化する。実 groovy
# 宣言の `name =` までの長さは十分下回る＝出力不変。実測: 200字で最悪 ~57ms。
GROOVY_LINE_CAP = 200

# Groovy: final 定数（static 任意・型任意）と一般代入左辺（限定子は剥がす）。
GROOVY_CONST_RE = re.compile(
    r"\b((?:public|protected|private|static|final)(?:\s+(?:public|protected|private|static|final))*)"
    r"\s+(?:[\w.$<>,\[\]\s]+?\s+)?([A-Za-z_]\w*)\s*=")
GROOVY_VAR_RE = re.compile(r"(?<![=!<>+\-*/%&|^])\b([A-Za-z_]\w*)\s*=(?!=)")
