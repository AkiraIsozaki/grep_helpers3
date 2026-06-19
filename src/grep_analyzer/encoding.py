"""文字コードを判定し決定的フォールバック鎖で復号する。decodeで絶対に落とさない。"""

import chardet

# utf-8 → 検出結果 → cp932/euc-jp → latin-1（置換・最終手段）
DEFAULT_FALLBACK = ["cp932", "euc-jp", "latin-1"]

# chardet がこの値未満の confidence で推測した検出は「要確認」とする（#3）。
# 誤コーデックでの strict 復号は成功し mojibake を出しても U+FFFD を残さないため
# 事後検知できない。せめて検出器自身が自信のない推測を顕在化させる。保守的な閾値で
# 通常の SJIS/EUC（十分な日本語があれば高 confidence）を巻き込まないようにする。
_LOW_CONFIDENCE = 0.5


def decode_bytes(data: bytes, fallback_chain: list[str], fast: bool = False) -> tuple[str, str, bool]:
    """(text, 使用エンコーディング, 置換が発生したか) を返す。

    手順: ① utf-8 厳格 → [② fast=True のとき fallback_chain 厳格（chardet 前短絡）] →
    ③ chardet 検出（全バイト1回）→ ④ fallback_chain 順に厳格 →
    ⑤ latin-1 + replace（必ず成功・置換フラグ True）。

    fast=True は SJIS 多数環境で chardet コストを省く opt-in 高速路。
    デフォルト False では従来と完全同一出力（default-OFF・golden テスト維持）。
    短い/曖昧な入力では chardet が誤検出し得る（既知の限界）。
    その場合も例外は出さず、置換発生時は encoding 列＋diagnostics の「要確認」で
    顕在化させる（呼び出し側責務）。
    """
    try:
        return data.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:
        pass

    if fast:
        for e in fallback_chain[:-1]:
            try:
                return data.decode(e), e, False
            except (UnicodeDecodeError, LookupError):
                continue

    det = chardet.detect(data)
    detected = det.get("encoding")
    if detected:
        try:
            text = data.decode(detected)
        except (UnicodeDecodeError, LookupError):
            text = None
        if text is not None:
            # confidence 欠落（stub 等）は従来どおり要確認にしない。低 confidence のみ顕在化。
            conf = det.get("confidence")
            low = conf is not None and conf < _LOW_CONFIDENCE
            return text, detected.lower(), low

    for enc in fallback_chain[:-1]:
        try:
            return data.decode(enc), enc, False
        except (UnicodeDecodeError, LookupError):
            continue

    last = fallback_chain[-1]
    return data.decode(last, errors="replace"), last, True


def decode_with_memo(memo: dict, abspath: str, data: bytes, fallback_chain, fast: bool = False):
    """decode_bytes のメモ化版。memo[abspath]=(enc,replaced) を再利用し chardet を省く。

    memo ヒット時は保存済み (enc, replaced) で再 decode（decode_bytes と同一テキストを得る）。
    codec 名非等価/再 decode 失敗は安全側に再計算へ降格。
    fast は memo ミス時のみ decode_bytes に転送（ヒット経路は stored codec で再 decode＝不変）。
    """
    hit = memo.get(abspath)
    if hit is not None:
        enc, replaced = hit
        try:
            return data.decode(enc, errors="replace" if replaced else "strict"), enc, replaced
        except (LookupError, UnicodeDecodeError):
            pass                              # codec名非等価等の保険＝再計算へ降格
    text, enc, replaced = decode_bytes(data, fallback_chain, fast=fast)
    memo[abspath] = (enc, replaced)
    return text, enc, replaced
