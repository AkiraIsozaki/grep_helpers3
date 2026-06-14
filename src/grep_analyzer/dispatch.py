"""ファイルの言語判定。"""

import os
import re

from grep_analyzer.embed_preprocess import _ANGULAR_RE

_EXT_MAP = {
    ".java": "java",
    ".sql": "sql",
    ".sh": "shell", ".ksh": "shell", ".bash": "shell",
    ".csh": "shell", ".tcsh": "shell",
    ".pc": "proc",
    ".c": "c", ".h": "c",
    ".pkb": "sql", ".pks": "sql", ".prc": "sql", ".fnc": "sql",
    ".trg": "sql", ".pls": "sql", ".plb": "sql",
    ".pl": "perl", ".pm": "perl", ".t": "perl",
    ".groovy": "groovy", ".gvy": "groovy", ".gradle": "groovy",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".py": "python",
    ".jsp": "jsp", ".jspf": "jsp", ".jspx": "jsp", ".tag": "jsp", ".tagx": "jsp",
}
# 言語判定に渡すサンプリング窓（バイト数相当の文字数）。EXEC SQL は長い preamble の
# 後に現れることがあり、4096 字では取りこぼす（test_dispatch の preamble テスト参照）。
# direct(pipeline) と scan/indirect(_scan) の両経路が同一窓で同一に分類するための
# 単一情報源とする（窓が食い違うと同一ファイルが経路により別言語に分類され列がブレる）。
LANG_SAMPLE_BYTES = 64 * 1024

_EXEC_SQL_RE = re.compile(r"\bEXEC\s+SQL\b", re.IGNORECASE)

# C リテラル/コメントを同字数空白に潰す dispatch 専用マスクである。
# MASK_SPECS["c"] は AST 化方針のため非対象（literal_masking.py 注記）。よって
# 言語判定ヒューリスティック（EXEC SQL search）専用にここで局所的にマスクする。
_C_LITERAL_RE = re.compile(
    r'"(?:\\.|[^"\\])*"' r"|'(?:\\.|[^'\\])*'" r"|//[^\n]*" r"|/\*.*?\*/",
    re.DOTALL)


def _mask_c_literals(text: str) -> str:
    return _C_LITERAL_RE.sub(lambda m: " " * len(m.group(0)), text)


# シェバンは第1物理行の1列目（先頭 BOM=U+FEFF 可）に #! が必須である。
_SHEBANG_RE = re.compile(r"^\ufeff?#!\s*(\S+)(?:\s+(\S+))?")
_BOURNE_INTERP = {"sh", "bash", "ksh", "dash"}
_CSHELL_INTERP = {"csh", "tcsh"}
_SHEBANG_LANG = {
    "sh": "shell", "bash": "shell", "ksh": "shell", "dash": "shell",
    "csh": "shell", "tcsh": "shell", "perl": "perl", "groovy": "groovy",
    "node": "javascript", "python": "python",
}
_VERSION_SUFFIX_RE = re.compile(r"\d[\d.]*$")


def _shebang_interp(content_sample: str) -> str | None:
    """第1物理行のシェバンから interpreter basename（版番号剥がし）を返す。"""
    first_line = content_sample.split("\n", 1)[0]
    m = _SHEBANG_RE.match(first_line)
    if m is None:
        return None
    interp = m.group(1).rsplit("/", 1)[-1]
    if interp == "env" and m.group(2):
        interp = m.group(2).rsplit("/", 1)[-1]
    return _VERSION_SUFFIX_RE.sub("", interp) or interp


def shebang_language(content_sample: str) -> str | None:
    """シェバンを言語名（shell/perl/groovy/javascript/python）に解決する。

    シェバン無し・対応外 interpreter（awk 等）の場合は None を返す。
    """
    interp = _shebang_interp(content_sample)
    return None if interp is None else _SHEBANG_LANG.get(interp)


def shebang_dialect(content_sample: str) -> str | None:
    """シェバンからシェル方言を返す。

    "bourne" / "cshell" / "other"（非シェル interpreter）/ None（シェバン無し）。
    `shebang_language` と同一の第1行解釈・版剥がし規則を共有する。
    """
    interp = _shebang_interp(content_sample)
    if interp is None:
        return None
    if interp in _BOURNE_INTERP:
        return "bourne"
    if interp in _CSHELL_INTERP:
        return "cshell"
    return "other"


def detect_language(path: str, content_sample: str, lang_map: dict[str, str]) -> str:
    """優先順位で言語を返す。

    1) --lang-map 2) 拡張子 3) シェバン（shell/perl/groovy 等）
    4) EXEC SQL ヒューリスティック 5) c フォールバック。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in lang_map:
        return lang_map[ext]
    lang = _EXT_MAP.get(ext)
    if lang == "shell":
        return "shell"
    if lang in ("c", "proc") or ext == ".h":
        if _EXEC_SQL_RE.search(_mask_c_literals(content_sample)):
            return "proc"
        return lang or "c"
    if ext in (".html", ".htm"):
        return "angular" if _ANGULAR_RE.search(content_sample) else "html"
    if lang is not None:  # java / sql / perl / groovy
        return lang
    # 拡張子が未知または無い: シェバン解決（手順3）→ EXEC SQL（手順4）→ c（手順5）
    sl = shebang_language(content_sample)
    if sl is not None:
        return sl
    if _EXEC_SQL_RE.search(_mask_c_literals(content_sample)):
        return "proc"
    return "c"


def extension_resolves_language(path: str, lang_map: dict[str, str]) -> bool:
    """拡張子または --lang-map だけで言語が確定するなら True（手順1〜2）。

    False のときのみシェバン検出（手順3）に進む。
    """
    ext = os.path.splitext(path)[1].lower()
    return ext in lang_map or ext in _EXT_MAP or ext in (".html", ".htm")


def detect_shell_dialect(path: str, content_sample: str) -> str:
    """Shell の方言（"bourne"/"cshell"）を返す。

    ① シェバン優先 ② 拡張子 ③ デフォルト bourne。
    言語判定とは独立に呼ばれ、既知シェル拡張子でもシェバンを必ず確認する。
    """
    sd = shebang_dialect(content_sample)
    if sd in ("bourne", "cshell"):
        return sd
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csh", ".tcsh"):
        return "cshell"
    return "bourne"
