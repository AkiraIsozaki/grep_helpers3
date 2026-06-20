"""snippet を縮約する（「上限と切り詰め」）。

ヒット行を中心に上下対称に拡張し、行数 LINE_MAX / 文字数 CHAR_MAX で
頭打ちにする。文字数は連結後 body の Python `len()`（コードポイント数）。
"""

SEP = " \\n "
ELLIPSIS = "…"
LINE_MAX = 12
CHAR_MAX = 800


def _escape_sep(line: str) -> str:
    """行中の区切り列 SEP(' \\n '=U+0020 005C 006E 0020) と同一 4 文字並びの
    \\(U+005C) を \\\\ へ二重化し、区切りと本文の曖昧化を防ぐ。

    snippet 出力の最終段（連結直前）で適用するのが契約である（#J）。truncation の
    後に escape することで、切り詰めが二重バックスラッシュを途中で割って中途半端な
    escape を残すことがない（escape は常に確定済みテキスト全体に対して 1 回だけ走る）。
    """
    return line.replace(SEP, " \\\\n ")


def _truncate_for_render(text: str, char_max: int) -> str:
    """raw text を「_render の escape 後の最終長が char_max を超えない」よう切り ELLIPSIS を足す。

    escape 後長が既に char_max 以下ならそのまま返す。SEP(4 文字)は _escape_sep で 5 文字へ
    膨らむため、raw 長だけで切ると escape 後に char_max を超え得る（M）。超過時は
    escape 後長 ≤ char_max-len(ELLIPSIS) となる最大 raw prefix を二分探索で求める。_escape_sep は
    単調増加なので二分が成立する。返り値は raw prefix＋ELLIPSIS（_render 側が後段で 1 回だけ
    escape する契約は維持）。
    """
    if len(_escape_sep(text)) <= char_max:
        return text
    budget = char_max - len(ELLIPSIS)
    if budget < 0:                        # ELLIPSIS すら入らない極小 char_max（本番 800 では未到達）
        return text[:max(0, char_max)]
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(_escape_sep(text[:mid])) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ELLIPSIS


def _render(rows: list[str], top_k: int, bot_k: int) -> str:
    body = SEP.join(_escape_sep(r) for r in rows)
    if top_k:
        body = f"{ELLIPSIS}(+{top_k}上行省略)" + body
    if bot_k:
        body = body + f"{ELLIPSIS}(+{bot_k}下行省略)"
    return body


def _line_count(lo: int, hi: int) -> int:
    """閉区間 [lo, hi] に含まれる行数を返す（hi < lo なら 0）。"""
    return hi - lo + 1 if hi >= lo else 0


def clamp_lines(lines: list[str], hit: int, line_max: int = LINE_MAX,
                char_max: int = CHAR_MAX) -> str:
    """選択範囲 lines をヒット中心に縮約して返す。

    hit は lines 内の 0 始まり index。
    サニタイズ・区切り衝突エスケープは呼び出し側（build_snippet）の責務。
    up_idx/down_idx は「次に取り込む候補行」。省略行数は未取込側の閉区間
    （上=[span_start, up_idx]、下=[down_idx, span_end]）の行数で表す。
    """
    span_start, span_end = 0, len(lines) - 1
    hit_text = lines[hit]
    out = [_truncate_for_render(hit_text, char_max)]
    up_idx, down_idx = hit - 1, hit + 1
    while True:
        if len(out) >= line_max:
            break
        progressed = False
        if up_idx >= span_start:
            cand = [lines[up_idx]] + out
            above = _line_count(span_start, up_idx - 1)   # up_idx 取込後に残る上行
            below = _line_count(down_idx, span_end)
            if len(cand) <= line_max and len(_render(cand, above, below)) <= char_max:
                out, up_idx, progressed = cand, up_idx - 1, True
        if len(out) >= line_max:
            break
        if down_idx <= span_end:
            cand = out + [lines[down_idx]]
            above = _line_count(span_start, up_idx)
            below = _line_count(down_idx + 1, span_end)   # down_idx 取込後に残る下行
            if len(cand) <= line_max and len(_render(cand, above, below)) <= char_max:
                out, down_idx, progressed = cand, down_idx + 1, True
        if not progressed:
            break
    top_k = _line_count(span_start, up_idx)
    bot_k = _line_count(down_idx, span_end)
    return _render(out, top_k, bot_k)
