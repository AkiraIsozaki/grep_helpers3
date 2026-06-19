"""TSV フィールドのサニタイズ規約を定める。

全制御文字（C0 U+0000–001F / DEL U+007F / C1 U+0080–009F）と
行/改ページ分割（U+2028 U+2029）を半角空白 1 個へ置換する `sanitize_field` を
提供する。書込本体は output_writer.py。
"""

# サニタイズ規約①: 全制御文字＋ U+2028/U+2029 を半角空白1個へ置換する。
# 旧集合（\t \r \n \v \f U+0085 U+2028 U+2029）を包含（C0⊂新集合・U+0085 は C1）。
# U+000A も空白化されるため split("\n")/data_sha256 の決定性は不変。
_SANITIZE_MAP = {c: " " for c in range(0x00, 0x20)}   # C0 制御
_SANITIZE_MAP[0x7F] = " "                             # DEL
_SANITIZE_MAP.update({c: " " for c in range(0x80, 0xA0)})  # C1 制御（U+0085 含む）
_SANITIZE_MAP[0x2028] = " "                           # LINE SEPARATOR
_SANITIZE_MAP[0x2029] = " "                           # PARAGRAPH SEPARATOR


def sanitize_field(cell: str) -> str:
    """フィールド内の全制御文字・行分割クラスを空白へ置換する。"""
    return cell.translate(_SANITIZE_MAP)


# サニタイズ規約②: 数式トリガ（CSV/TSV injection）の無害化。
# Excel/LibreOffice はセル先頭が = + - @ だと数式として評価し、DDE/HYPERLINK 等で
# コード実行・情報漏洩に至る。出力は BOM 付きで Excel が自動的に数式解釈するため、
# untrusted ソース由来セル（snippet/via_symbol 等）の先頭をクオートで無害化する。
# 先頭 TAB/CR は sanitize_field が空白化済みなので {= + - @} のみ対象。
_FORMULA_TRIGGERS = frozenset("=+-@")


def neutralize_formula(cell: str) -> str:
    """セル先頭が数式トリガなら単一引用符を前置して無害化する（決定的）。

    sanitize_field の後段で _data_line から全列に適用する（書込側＝data_sha 側で
    共有するため round-trip は不変）。引用符は Excel/Calc が取り込み時にテキスト
    マーカとして扱い、生 TSV 上はデータの一部として残る。
    """
    if cell and cell[0] in _FORMULA_TRIGGERS:
        return "'" + cell
    return cell
