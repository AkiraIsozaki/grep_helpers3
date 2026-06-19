"""input/*.grep の行をバイト境界でパースする。
"""

import re

_LINE_RE = re.compile(rb"^(?P<path>.*?):(?P<lineno>\d+):(?P<content>.*)$", re.DOTALL)


def parse_grep_line(line: bytes) -> tuple[bytes, int, bytes] | None:
    """`path:lineno:content` を**バイト列のまま**最左の `:<数字>:` 境界で分割する。

    パス部のバイトを保つことで、UTF-8 として不正なファイル名（SJIS 混在等）でも
    呼び出し側が os.fsdecode で FS と一致するパスを復元できる（テキスト復号では
    UTF-8 ファイルシステムへ再エンコードしても元バイトに戻らない）。
    復号方針（パス＝fsdecode／content＝文字コード判定）は呼び出し側責務。

    **前提と既知の制約（H4・意図的トレードオフ）**: 入力は grep -rn / rg の Unix 相対パス
    （`path:lineno:content`）を想定し、パス部は `:<数字>:` を含まないものとする。最左の
    `:<数字>:` を境界に取るため、パス自体に `:<数字>:` が現れる入力（Windows ドライブ
    レター `C:1:foo.c:...`、行番号入りファイル名など）は path/lineno を誤分割し得る。
    対象が Unix 相対パスのみなら実害はない。最右境界・ドライブレター考慮は新たな誤分割
    （content 先頭が `数字:` で始まる等）を招くため採らない。

    不一致なら None を返す（呼び出し側が diagnostics に回す）。
    """
    m = _LINE_RE.match(line.rstrip(b"\r\n"))
    if m is None:
        return None
    return m.group("path"), int(m.group("lineno")), m.group("content")
