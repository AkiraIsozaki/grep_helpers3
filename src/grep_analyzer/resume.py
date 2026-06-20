"""kw 単位 resume の完了判定を行う（完了判定1〜5）。"""

import hashlib
import json
from pathlib import Path

from grep_analyzer import __version__
from grep_analyzer.budget import _ITEMS_PER_MB
from grep_analyzer.output_writer import _blob_from_data_rows, _rows_from_part_text


def compute_inputs_fingerprint(grep_bytes: bytes, source_root, opts) -> str:
    """行に影響する入力（.grep 本文・source_root・行を左右する opts・stoplist 内容）の
    決定的指紋を返す（H1）。

    resume が「前回と入力もオプションも同じ」ことを保証するために使う。出力（per-keyword
    TSV の行）を変えない opts（jobs/progress/spill_dir/decode_cache*/use_ripgrep/
    ripgrep_threshold_bytes/diagnostics_detail_limit/perkw_diag/force_*/resume）は含めない。
    output_encoding/max_rows_per_part は is_complete が個別照合するため重複させない。
    """
    try:
        stoplist = Path(opts.stoplist_path).read_bytes() if opts.stoplist_path else b""
    except OSError:
        stoplist = b""
    payload = {
        "grep": hashlib.sha256(grep_bytes).hexdigest(),
        "source_root": str(Path(source_root).resolve()),
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
    data_rows: list[str] = []
    try:
        for part in m.get("parts", []):
            f = out_dir / part["name"]
            if not f.is_file():                                   # 条件2
                return False
            rows = _rows_from_part_text(f.read_text(enc))
            if len(rows) != part.get("rows"):                     # 条件3
                return False
            data_rows += rows
    except (KeyError, TypeError, UnicodeDecodeError, OSError, LookupError):
        return False
    sha = hashlib.sha256(_blob_from_data_rows(data_rows)).hexdigest()
    if sha != m.get("data_sha256"):                           # 条件4（書込側と同一関数）
        return False
    if m.get("tool_version") != __version__:                  # 条件5
        return False
    if m.get("items_per_mb") != _ITEMS_PER_MB:                # 条件5
        return False
    return True
