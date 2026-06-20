"""埋め込みトラック（JSP/Angular）の逆マスク＋ホスト写像。

行数（改行位置）のみを保証する逆マスク（lineno 写像に必須）。
proc_preprocess へは単方向依存（循環を避けるため）。
"""

import re

from grep_analyzer.patterns.literal_masking import blank_keep_newlines
from grep_analyzer.proc_preprocess import mask_exec_sql

_JSP_COMMENT = re.compile(r"<%--.*?--%>", re.DOTALL)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_JSP_DIRECTIVE = re.compile(r"<%@.*?%>", re.DOTALL)
_JSP_ACTION = re.compile(r"</?jsp:[^>]*?/?>", re.DOTALL)
_JSP_CODE = re.compile(r"<%[=!]?(.*?)%>", re.DOTALL)
_EL = re.compile(r"[$#]\{(.*?)\}", re.DOTALL)
# JSTL 関数接頭辞（fn: 等）を除去する。best-effort。
# EL 内の URL プロトコル `http:` や三項 `b:` も除去しうるが稀なため許容。
_EL_PREFIX = re.compile(r"\b[A-Za-z_]\w*:")


def extract_jsp_java(source: str) -> str:
    """JSP から java host が読める区間だけ残し他を空白化（行数保存）。"""
    out = list(blank_keep_newlines(source))
    masked = source
    for rx in (_JSP_COMMENT, _HTML_COMMENT, _JSP_DIRECTIVE, _JSP_ACTION):
        masked = rx.sub(lambda m: blank_keep_newlines(m.group(0)), masked)
    for m in _JSP_CODE.finditer(masked):
        for i in range(m.start(1), m.end(1)):
            out[i] = source[i]
    for m in _EL.finditer(masked):
        for i in range(m.start(1), m.end(1)):
            out[i] = source[i]
        inner = source[m.start(1):m.end(1)]
        for pm in _EL_PREFIX.finditer(inner):
            for i in range(m.start(1) + pm.start(), m.start(1) + pm.end()):
                out[i] = " "
    return "".join(out)


def jsp_region_span(file_text: str, lineno: int):
    """ヒット行を含む <%…%> 系ブロックの行スパン [s,e] を返す（0始まり）。

    区間外は None（呼出側で 1 行フォールバック）。
    区間検出は extract_jsp_java と同じ _JSP_CODE 正規表現を共有する（既知限界）。
    """
    hit = lineno - 1
    for m in _JSP_CODE.finditer(file_text):
        start = file_text.count("\n", 0, m.start())
        end = file_text.count("\n", 0, m.end())
        if start <= hit <= end:
            return (start, end)
    return None


# Angular 固有束縛マーカである（{{ 単独は Vue/Handlebars と重複するため含めない）
_ANGULAR_RE = re.compile(
    r"""\*ng[\w-]+|\[\(?[\w.$-]+\)?\]\s*=|\([\w.$-]+\)\s*=|routerLink|formControl|ngModel""")

_NG_INTERP = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
# [prop]= / [(two-way)]= / (event)= / *dir=  の属性。値は " か ' で囲まれる。
_NG_ATTR = re.compile(
    r"""(?:\[\(?[\w.$-]+\)?\]|\([\w.$-]+\)|\*[\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""",
    re.DOTALL)
_NG_PIPE = re.compile(r"(?<!\|)\|(?!\|)")               # 単一 | （|| は除外）


def _ng_normalize(expr: str) -> str:
    """式断片の best-effort 正規化。ngFor の of→= で1字縮む以外は長さを保つ。"""
    head = expr.split(";", 1)[0]
    head = re.sub(r"\bof\b", "=", head)
    m = _NG_PIPE.search(head)
    if m is not None:
        head = head[:m.start()]
    return head


def extract_angular_ts(source: str) -> str:
    """Angular テンプレから TypeScript host が読める式だけ残す（行数保存）。"""
    out = list(blank_keep_newlines(source))
    masked = _HTML_COMMENT.sub(lambda m: blank_keep_newlines(m.group(0)), source)

    def _emit(raw_start: int, raw_expr: str):
        # norm が raw_expr より短い場合（of→= 縮約・パイプ除去）、残余位置は
        # out 初期化済みの空白のまま（行数は不変）。
        norm = _ng_normalize(raw_expr)
        for j, ch in enumerate(norm):
            if raw_start + j < len(out):
                out[raw_start + j] = ch

    for m in _NG_INTERP.finditer(masked):
        _emit(m.start(1), source[m.start(1):m.end(1)])
    for m in _NG_ATTR.finditer(masked):
        gi = 1 if m.group(1) is not None else 2
        _emit(m.start(gi), source[m.start(gi):m.end(gi)])
    return "".join(out)


# .component.ts の inline angular template 検出（template: `...`）。
# templateUrl: は `\s*:` に非マッチ、styles: [`...`] も同様。best-effort。
_INLINE_TEMPLATE = re.compile(r"\btemplate\s*:\s*`(.*?)`", re.DOTALL)


def inline_template_spans(ts_source: str) -> list[tuple[int, int]]:
    """inline template 内容（group1）の行スパン [(s,e)] を返す（0始まり）。"""
    return [(ts_source.count("\n", 0, m.start(1)), ts_source.count("\n", 0, m.end(1)))
            for m in _INLINE_TEMPLATE.finditer(ts_source)]


_SPANS_CACHE_KEY = "_inline_template_spans"


def _cached_inline_spans(ts_source: str, cache: dict | None) -> list[tuple[int, int]]:
    """inline_template_spans を file 単位 cache でメモ化する（#O）。

    cache は classify_hit/build_snippet が同一ファイル内で共有する dict（parse 木と
    同居）。language 名キー（"typescript" 等）と衝突しない専用キーで spans を保持し、
    typescript の各ヒットで全文 DOTALL 正規表現を掛け直すのを 1 回に集約する。
    """
    if cache is None:
        return inline_template_spans(ts_source)
    if _SPANS_CACHE_KEY not in cache:
        cache[_SPANS_CACHE_KEY] = inline_template_spans(ts_source)
    return cache[_SPANS_CACHE_KEY]


def extract_inline_angular(ts_source: str) -> str:
    """inline template 領域のみ angular 式を残し他を空白化（行数保存）。"""
    kept = list(blank_keep_newlines(ts_source))
    for m in _INLINE_TEMPLATE.finditer(ts_source):
        for i in range(m.start(1), m.end(1)):
            kept[i] = ts_source[i]
    return extract_angular_ts("".join(kept))


def effective_language(file_language: str, file_text: str, lineno: int,
                       cache: dict | None = None) -> str:
    """ヒット行の実効言語。typescript の inline template 行のみ angular_inline、
    それ以外は file_language をそのまま返す。

    cache を渡すと inline template span 計算を file 単位でメモ化する（#O）。
    """
    if file_language != "typescript":
        return file_language
    hit = lineno - 1
    for s, e in _cached_inline_spans(file_text, cache):
        if s <= hit <= e:
            return "angular_inline"
    return "typescript"


_HOST_GRAMMAR = {"proc": "c", "jsp": "java", "angular": "typescript",
                 "angular_inline": "typescript"}


def host_grammar(language: str) -> str:
    """埋め込み言語→ホスト grammar 名。既存言語は恒等。"""
    return _HOST_GRAMMAR.get(language, language)


def host_source(language: str, source: str) -> str:
    """埋め込み言語→ホストが読める逆マスク済ソース。既存言語は恒等。"""
    if language == "proc":
        return mask_exec_sql(source)
    if language == "jsp":
        return extract_jsp_java(source)
    if language == "angular":
        return extract_angular_ts(source)
    if language == "angular_inline":
        return extract_inline_angular(source)
    return source
