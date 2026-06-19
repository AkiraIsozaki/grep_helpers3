"""snippet を縮約する（「上限と切り詰め」）。

ヒット行を中心に上下対称に拡張し、行数 LINE_MAX / 文字数 CHAR_MAX で
頭打ちにする。文字数は連結後 body の Python `len()`（コードポイント数）。
"""

SEP = " \\n "
ELL = "…"
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
    """raw text を「_render の escape 後の最終長が char_max を超えない」よう切り ELL を足す。

    SEP(4 文字)は _escape_sep で 5 文字へ膨らむため、raw 長だけで切ると escape 後に
    char_max を超え得る（M）。escape 後長 ≤ char_max-len(ELL) となる最大 raw prefix を
    二分探索で求める。_escape_sep は単調増加なので二分が成立する。返り値は raw prefix＋ELL
    （_render 側が後段で 1 回だけ escape する契約は維持）。
    """
    budget = char_max - len(ELL)
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(_escape_sep(text[:mid])) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ELL


def _render(rows: list[str], top_k: int, bot_k: int) -> str:
    body = SEP.join(_escape_sep(r) for r in rows)
    if top_k:
        body = f"{ELL}(+{top_k}上行省略)" + body
    if bot_k:
        body = body + f"{ELL}(+{bot_k}下行省略)"
    return body


def clamp_lines(lines: list[str], hit: int, line_max: int = LINE_MAX,
                char_max: int = CHAR_MAX) -> str:
    """選択範囲 lines をヒット中心に縮約して返す。

    hit は lines 内の 0 始まり index。
    サニタイズ・区切り衝突エスケープは呼び出し側（build_snippet）の責務。
    """
    span_start, span_end = 0, len(lines) - 1
    hit_text = lines[hit]
    # escape 後長で判定・切詰する（SEP 膨張で raw≤char_max でも超過し得るため・M）。
    out = ([_truncate_for_render(hit_text, char_max)]
           if len(_escape_sep(hit_text)) > char_max else [hit_text])
    up_idx, down_idx = hit - 1, hit + 1
    while True:
        if len(out) >= line_max:
            break
        progressed = False
        if up_idx >= span_start:
            cand = [lines[up_idx]] + out
            above_count = (up_idx - 1) - span_start + 1 if (up_idx - 1) >= span_start else 0
            below_count = span_end - down_idx + 1 if down_idx <= span_end else 0
            if len(cand) <= line_max and len(_render(cand, above_count, below_count)) <= char_max:
                out, up_idx, progressed = cand, up_idx - 1, True
        if len(out) >= line_max:
            break
        if down_idx <= span_end:
            cand = out + [lines[down_idx]]
            above_count = up_idx - span_start + 1 if up_idx >= span_start else 0
            below_count = span_end - (down_idx + 1) + 1 if (down_idx + 1) <= span_end else 0
            if len(cand) <= line_max and len(_render(cand, above_count, below_count)) <= char_max:
                out, down_idx, progressed = cand, down_idx + 1, True
        if not progressed:
            break
    top_k = up_idx - span_start + 1 if up_idx >= span_start else 0
    bot_k = span_end - down_idx + 1 if down_idx <= span_end else 0
    return _render(out, top_k, bot_k)
