"""文字コードを判定し決定的フォールバック鎖で復号する。decodeで絶対に落とさない。"""

import chardet

# utf-8 → 検出結果 → cp932/euc-jp → latin-1（置換・最終手段）
DEFAULT_FALLBACK = ["cp932", "euc-jp", "latin-1"]

# chardet の SJIS 系検出名は cp932 へ正規化する。Python の shift_jis codec は
# cp932 と写像が異なり（0x8160: U+301C vs U+FF5E、0x817C: U+2212 vs U+FF0D）、
# NEC/IBM 拡張文字を含むファイルだけ fallback の cp932 に落ちる結果、同一コーパス内で
# 同じバイトが 2 種の Unicode に割れる。MS932 主体の実運用では cp932 が正である。
_CP932_ALIASES = frozenset({
    "shift_jis", "shift-jis", "sjis", "s_jis", "shiftjis",
    "windows-31j", "cs-windows-31j", "ms932", "ms_kanji", "mskanji", "cp932",
})

# 1 バイト系 codec はほぼ全バイト列で strict decode が成功するため、chardet が
# これらを返したときは fallback 鎖の多バイト codec の strict 成功を優先する
# （短い SJIS 断片が Windows-1252 等と誤検出され「要確認」なしの silent mojibake に
# なるのを防ぐ）。多バイト側が全滅なら検出結果をそのまま使う（従来経路）。
_SINGLE_BYTE_SUSPECTS = frozenset({
    "windows-1250", "windows-1251", "windows-1252", "windows-1253",
    "windows-1254", "windows-1255", "windows-1256", "windows-1257",
    "cp1250", "cp1251", "cp1252", "cp1253", "cp1254", "cp1255", "cp1256",
    "iso-8859-1", "iso-8859-2", "iso-8859-5", "iso-8859-7", "iso-8859-8",
    "iso-8859-9", "iso-8859-13", "iso-8859-15", "latin-1", "latin1",
    "macroman", "mac-roman", "maccyrillic", "mac-cyrillic",
    "koi8-r", "koi8-u", "tis-620", "cp874",
})

def _japanese_score(text: str) -> int:
    """日本語スクリプト（かな・CJK・全角）の文字数を数える（多バイト復号の妥当性指標）。"""
    return sum(1 for ch in text
               if 0x3040 <= ord(ch) <= 0x30FF      # ひらがな・カタカナ
               or 0x4E00 <= ord(ch) <= 0x9FFF      # CJK 統合漢字
               or 0xFF01 <= ord(ch) <= 0xFF5E)     # 全角英数記号


def _latin_score(text: str) -> int:
    """アクセント付き Latin（U+00C0〜U+024F）の文字数を数える（1 バイト系復号の妥当性指標）。"""
    return sum(1 for ch in text if 0x00C0 <= ord(ch) <= 0x024F)


def _prefer_multibyte(data: bytes, detected_norm: str, fallback_chain):
    """1 バイト系検出時、多バイト fallback の復号が「日本語として尤もらしい」場合のみ
    そちらを採る。(text, enc, replaced) か None（従来経路へ）を返す。

    1 バイト系 codec はほぼ全バイト列で strict 成功するため判定力が無い。一方で
    無条件に多バイトを優先すると、真正 Latin テキスト（café 等）まで cp932 の
    偶然成功で誤復号する。日本語スコア > Latin スコアのときだけ覆す（決定的）。
    """
    for enc in fallback_chain[:-1]:
        if enc.lower() in _SINGLE_BYTE_SUSPECTS:
            continue
        try:
            mb_text = data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        jp = _japanese_score(mb_text)
        if jp == 0:
            return None
        try:
            sb_text = data.decode(detected_norm)
        except (UnicodeDecodeError, LookupError):
            sb_text = ""
        if jp > _latin_score(sb_text):
            return mb_text, enc, False
        return None
    return None


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
    # 空鎖は既定鎖へ復帰する。ここが全経路（direct/seed/scan/finalize/worker）の
    # 合流点であり、末尾 fallback_chain[-1] の IndexError を構造的に防ぐ。
    if not fallback_chain:
        fallback_chain = DEFAULT_FALLBACK
    try:
        return data.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:
        pass

    if fast:
        for enc in fallback_chain[:-1]:
            try:
                return data.decode(enc), enc, False
            except (UnicodeDecodeError, LookupError):
                continue

    det = chardet.detect(data)
    detected = det.get("encoding")
    if detected:
        detected_norm = detected.lower()
        if detected_norm in _CP932_ALIASES:
            detected_norm = "cp932"           # SJIS 系は cp932 写像へ統一
        if detected_norm in _SINGLE_BYTE_SUSPECTS:
            preferred = _prefer_multibyte(data, detected_norm, fallback_chain)
            if preferred is not None:
                return preferred
        try:
            text = data.decode(detected_norm)
        except (UnicodeDecodeError, LookupError):
            text = None
        if text is not None:
            # confidence 欠落（stub 等）は従来どおり要確認にしない。低 confidence のみ顕在化。
            conf = det.get("confidence")
            low = conf is not None and conf < _LOW_CONFIDENCE
            return text, detected_norm, low

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
