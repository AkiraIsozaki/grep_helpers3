"""kw 単位 resume の完了判定を行う（完了判定1〜5）。"""

import hashlib
import json
import os
from pathlib import Path

from grep_analyzer import __version__
from grep_analyzer.budget import _ITEMS_PER_MB
from grep_analyzer.output_writer import _rows_from_part_text, data_rows_sha256


def compute_source_state(files) -> str:
    """walk 受理ファイルの (relpath, mtime_ns, size) 集約ハッシュを返す。

    ソース本体の変更（snippet/分類/間接追跡を左右する）を resume の指紋に反映させる。
    decode_cache が (mtime,size) で自動失効するのと対称の失効条件である。
    既知の制限: walk 除外（--exclude/サイズ超過等）だが direct ヒットは持つファイルの
    変更は検知しない（.grep 側の再生成で検知される想定）。
    """
    h = hashlib.sha256()
    for relpath, abspath in files:            # walk は決定的ソート順で列挙する
        try:
            st = os.stat(abspath)
            sig = f"{st.st_mtime_ns}\0{st.st_size}"
        except OSError:
            sig = "gone"                      # walk 後に消えた: 消えたこと自体を状態にする
        h.update(f"{relpath}\0{sig}\n".encode("utf-8", "surrogatepass"))
    return h.hexdigest()


def compute_inputs_fingerprint(grep_bytes: bytes, source_root, opts,
                               source_state: str = "") -> str:
    """行に影響する入力（.grep 本文・source_root・ソース状態・行を左右する opts・
    stoplist 内容）の決定的指紋を返す（H1）。

    resume が「前回と入力もオプションも同じ」ことを保証するために使う。出力（per-keyword
    TSV の行）を変えない opts（jobs/progress/spill_dir/decode_cache*/use_ripgrep/
    ripgrep_threshold_bytes/diagnostics_detail_limit/perkw_diag/force_*/resume）は含めない。
    output_encoding/max_rows_per_part は is_complete が個別照合するため重複させない。
    source_state は compute_source_state の集約ハッシュ（ソース編集後の stale 出力を
    「完了」と誤認しないため）。
    """
    # 読込失敗を b"" に縮退させると「stoplist なし」と同一指紋になり、stoplist 未適用の
    # 旧出力を resume が完了扱いで採用してしまう。CLI が起動時に存在検証済みなので、
    # ここでの失敗は run 中の消失＝異常であり OSError をそのまま伝播して fail-stop する。
    stoplist = Path(opts.stoplist_path).read_bytes() if opts.stoplist_path else b""
    payload = {
        "grep": hashlib.sha256(grep_bytes).hexdigest(),
        "source_root": str(Path(source_root).resolve()),
        "source_state": source_state,
        "stoplist": hashlib.sha256(stoplist).hexdigest(),
        "opts": {
            "max_depth": opts.max_depth,
            "min_specificity": opts.min_specificity,
            "lang_map": sorted(opts.lang_map.items()),
            "include": list(opts.include),
            "exclude": list(opts.exclude),
            "follow_symlinks": bool(opts.follow_symlinks),
            "max_file_bytes": opts.max_file_bytes,
            "max_symbols": opts.max_symbols,
            "max_paths": opts.max_paths,
            "memory_limit_mb": opts.memory_limit_mb,
            "max_passes": opts.max_passes,
            "encoding_fallback": list(opts.encoding_fallback),
            "fast_encoding": bool(opts.fast_encoding),
        },
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8", "surrogatepass")).hexdigest()


def is_complete(out_dir: Path, keyword: str, opts,
                inputs_fingerprint: "str | None" = None) -> bool:
    """keyword の出力が完了済みかを manifest・part 実体・sha 照合で判定する。

    判定条件: (1) manifest 存在・正形、(2) 入力指紋一致、(3) 出力設定
    （encoding/max_rows_per_part）一致、(4) 全 part 実在・行数一致・data_sha256
    一致、(5) tool_version / items_per_mb 一致。いずれか不成立は False（再処理）。
    """
    out_dir = Path(out_dir)
    mpath = out_dir / f"{keyword}.manifest.json"
    if not mpath.is_file():                                   # 条件1
        return False
    try:
        m = json.loads(mpath.read_text("utf-8"))
    except (ValueError, OSError):
        return False
    if not isinstance(m, dict):                                # valid JSON だが dict でない破損形
        return False
    # 入力指紋照合（H1）: 入力 .grep や行に影響する opts が変われば未完了扱いで再処理する。
    # 旧 manifest（指紋欠落）は None≠指紋 で不一致＝再実行。inputs_fingerprint=None
    # （呼出側が指紋を渡さない後方互換経路）のときは従来どおり指紋照合しない。
    if inputs_fingerprint is not None and m.get("inputs_fingerprint") != inputs_fingerprint:
        return False
    # 出力を変えるオプションを明示照合。data_sha256 は正規化 utf-8 のデータ行のみで
    # partition/encoding 構成に不感なため、ここで別途照合する。
    # 旧 manifest（max_rows_per_part 欠落）は None≠int で不一致＝未完了扱い（再実行）。
    if m.get("encoding", "utf-8-sig") != opts.output_encoding:
        return False
    if m.get("max_rows_per_part") != opts.max_rows_per_part:
        return False
    enc = m.get("encoding", "utf-8-sig")
    # sha は part 単位で読み・ストリーミングで畳む（全 part の data_rows を同時に
    # 実体化すると完了判定だけで出力サイズ級のメモリを食う）。条件2/3 の不成立は
    # bad フラグで generator から伝える（sha は捨てられ False になる）。
    bad: list[bool] = []

    def _iter_part_rows():
        for part in m.get("parts", []):
            f = out_dir / part["name"]
            if not f.is_file():                                   # 条件2
                bad.append(True)
                return
            rows = _rows_from_part_text(f.read_text(enc))
            if len(rows) != part.get("rows"):                     # 条件3
                bad.append(True)
                return
            yield from rows

    try:
        sha = data_rows_sha256(_iter_part_rows())
    except (KeyError, TypeError, UnicodeDecodeError, OSError, LookupError):
        return False
    if bad or sha != m.get("data_sha256"):                    # 条件4（書込側と同一関数）
        return False
    if m.get("tool_version") != __version__:                  # 条件5
        return False
    if m.get("items_per_mb") != _ITEMS_PER_MB:                # 条件5
        return False
    return True
