"""出力確定モジュール。

安定ソート→正規化→part分割→各part原子書込→manifest原子確定→孤児クリーン。
正規形は _canonical_data_blob に一元化（書込側=完了判定=テストが共有）。
"""

import codecs
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

from grep_analyzer import __version__
from grep_analyzer.budget import _ITEMS_PER_MB
from grep_analyzer.model import TSV_COLUMNS, Hit, sort_key
from grep_analyzer.tsv import neutralize_formula, sanitize_field


def _data_line(h: Hit) -> str:
    """1 データ行を生成する（sanitize_field→数式ガード後にタブ結合）。"""
    return "\t".join(neutralize_formula(sanitize_field(c)) for c in h.to_row())


def _blob_from_data_rows(data_rows: list[str]) -> bytes:
    """データ行列→正規バイト列（唯一の正規化終端）。書込側・完了判定側が共有する。

    末尾改行無・LF 連結・"utf-8"（BOM 無 codec）。
    surrogate（FS 走査由来パス等）は errors="replace" で置換し、_part_bytes と同規約に
    揃えることで書込側 sha・完了判定側 sha・TSV 実体の round-trip を一致させる。
    """
    return "\n".join(data_rows).encode("utf-8", errors="replace")


def _canonical_data_blob(ordered: list[Hit]) -> bytes:
    """ソート済 Hit を正規バイト列へ変換する。書込側経路（_blob_from_data_rows を共有）。"""
    return _blob_from_data_rows([_data_line(h) for h in ordered])


def _persisted_rows_iter(ordered: list[Hit], enc: str):
    """output_encoding で実際に永続化される data 行（非可逆置換を反映）を yield する（C3）。

    resume は part を output_encoding で読み戻して data_rows を復元する。data_sha256 を
    utf-8 原文で計算すると、cp932 等の lossy 出力で非表現文字が `?` に置換された分だけ
    書込側 sha と resume 側 sha が恒久的に食い違い、完了判定が永久 False になる。
    そこで sha も「encode(enc,replace)→decode(enc)」を通した姿で計算し、resume の復元と
    一致させる。codec は本用途（utf-8/utf-8-sig/cp932/euc-jp/latin-1）ではいずれも文字
    独立（utf-8-sig の BOM は encode 付与→decode 除去で行単位でも恒等）なので、
    全行 join で往復させた旧実装と行単位往復は同一結果。lossless（utf-8 系）では
    恒等＝従来の data_sha256 とバイト不変。generator にすることで数 GB 級 TSV でも
    全行 join の巨大 str/bytes を実体化しない。
    """
    for h in ordered:
        line = _data_line(h)
        yield line.encode(enc, errors="replace").decode(enc)


def data_rows_sha256(rows) -> str:
    """データ行 iterable の正規 sha256 を返す（書込側・resume 完了判定が共有する）。

    sha256(_blob_from_data_rows(list(rows))) とバイト同値だが、行を LF 区切りで
    逐次畳むため出力サイズ分の blob を実体化しない（utf-8 の errors="replace" は
    文字独立なので行単位 encode と全体 encode は一致する）。
    """
    h = hashlib.sha256()
    first = True
    for row in rows:
        if not first:
            h.update(b"\n")
        h.update(row.encode("utf-8", errors="replace"))
        first = False
    return h.hexdigest()


def _rows_from_part_text(text: str) -> list[str]:
    """part 1 本のデコード済テキストからデータ行列を取り出す。

    _part_bytes の書込形式（`"\\n".join([header]+data_lines)+"\\n"`）の厳密逆：
    先頭 BOM 除去 → split("\\n") → 書込時に付与した末尾 LF 由来の空要素を 1 個だけ
    除去 → 先頭ヘッダ 1 行除去。
    splitlines() は使わない（書込が LF 連結である以上その厳密逆は LF split が正）。
    rstrip("\\n") ではなく末尾空要素を 1 個だけ剥がすことで、データ行が空文字列で
    終わる場合でも round-trip が厳密に保たれる（round-trip の正しさを「lineno 列が
    常に非空」というスキーマ不変条件に依存させない）。
    decode 済 utf-8-sig は BOM 自動除去だが、防御的に先頭 U+FEFF も剥がす。
    """
    if text and text[0] == "\ufeff":   # 防御的 BOM 除去（明示）
        text = text[1:]
    lines = text.split("\n")
    if lines and lines[-1] == "":      # 書込時の末尾 LF 由来の空要素を 1 個だけ除去
        lines.pop()
    return lines[1:]  # 先頭はヘッダ


def _atomic_write_stream(path: "Path", chunks) -> None:
    """唯一の原子書込プリミティブである（mkstemp->fsync->os.replace で不可分置換）。

    chunks は bytes の iterable。GB 級 part を単一 blob として実体化せず書けるよう
    ストリーミングで受ける。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # prefix は識別の便宜にすぎず、一意性は mkstemp が担保する。長大 keyword で
    # temp 名（{name}.{rand}.tmp）が NAME_MAX(255B) を超えないよう FS バイト長で
    # 切り詰める。fsencode/fsdecode（surrogateescape）は SJIS 由来のサロゲート混じり
    # keyword でも落ちない（マルチバイト途中の切断はサロゲートとして FS へ往復可能）。
    prefix = os.fsdecode(os.fsencode(path.name)[:120]) + "."
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            for chunk in chunks:
                f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _atomic_write(path: "Path", data: bytes) -> None:
    """bytes 一括の原子書込（_atomic_write_stream の単一チャンク形）。"""
    _atomic_write_stream(path, (data,))


def _fsync_dir(d: "Path") -> None:
    fd = os.open(str(d), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _part_bytes(header: str, data_rows: list[str], encoding: str) -> bytes:
    """part 1 本の正規バイト列（参照実装・テストの正）。書込は streaming 版を使う。"""
    return ("\n".join([header] + data_rows) + "\n").encode(
        encoding, errors="replace")


def _iter_part_bytes(header: str, data_rows, encoding: str):
    """_part_bytes と同一のバイト列を行単位チャンクで yield する（blob 非実体化）。

    incremental encoder は utf-8-sig の BOM を先頭チャンクにのみ付与するため、
    チャンク連結は全文一括 encode とバイト同値である（文字独立 codec 前提＝
    _persisted_rows_iter と同じ契約）。
    """
    encoder = codecs.getincrementalencoder(encoding)("replace")
    yield encoder.encode(header)
    for row in data_rows:
        yield encoder.encode("\n" + row)
    yield encoder.encode("\n", True)          # final=True で encoder を確定する


def _previous_part_names(out_dir: "Path", keyword: str) -> set:
    """既存 manifest が指す part 名集合を返す（旧 run の孤児削除対象・無ければ空集合）。

    glob（`{keyword}.part*.tsv`）は別 keyword の出力（例: keyword "foo" の glob が
    keyword "foo.part5" の `foo.part5.tsv` に当たる）を巻き込んで誤削除する（H3）。
    削除対象を「この keyword の旧 manifest が実際に列挙した part 名」だけに厳密化する。
    """
    mpath = out_dir / f"{keyword}.manifest.json"
    try:
        m = json.loads(mpath.read_text("utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(m, dict):
        return set()
    names = set()
    for p in m.get("parts", []):
        if isinstance(p, dict) and isinstance(p.get("name"), str):
            names.add(p["name"])
    return names


def _write_manifest(out_dir: "Path", keyword: str, manifest: dict) -> None:
    """manifest を原子確定（テストの monkeypatch フック点）。"""
    # keyword（=.grep 名）に surrogate が混じっても落とさない（errors="replace"）。
    # ensure_ascii=False は surrogate を str のまま残すため strict だと encode で倒れる。
    blob = json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":")).encode("utf-8", errors="replace")
    _atomic_write(out_dir / f"{keyword}.manifest.json", blob)


def finalize(out_dir: "Path", keyword: str, rows: "list[Hit]", opts,
             inputs_fingerprint: "str | None" = None) -> None:
    """keyword の全 Hit を安定ソートし TSV（必要なら part 分割）と manifest を確定する。

    書込は全て原子的（_atomic_write）で、manifest を最後に確定してから旧 run の
    孤児 part を削除する。inputs_fingerprint は resume の完了判定（H1）に焼き込む。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 新 manifest で上書きする前に、旧 run の part 名を控える（孤児削除に使う・H3）。
    prev_part_names = _previous_part_names(out_dir, keyword)
    ordered = sorted(rows, key=sort_key)
    total = len(ordered)
    rows_per_part = opts.max_rows_per_part
    nparts = 1 if total <= rows_per_part else math.ceil(total / rows_per_part)
    width = max(2, len(str(nparts)))
    header = "\t".join(TSV_COLUMNS)
    enc = opts.output_encoding
    # data_sha256 は「実際に enc で永続化される姿」で計算する（lossy 出力でも resume が
    # 読み戻した data_rows と一致させ完了判定を成立させる・C3）。lossless では従来と不変。
    data_sha = data_rows_sha256(_persisted_rows_iter(ordered, enc))

    parts_meta = []
    if nparts == 1:
        name = f"{keyword}.tsv"
        _atomic_write_stream(
            out_dir / name,
            _iter_part_bytes(header, (_data_line(h) for h in ordered), enc))
        parts_meta.append({"name": name, "rows": total})
    else:
        for i in range(nparts):
            chunk = ordered[i * rows_per_part:(i + 1) * rows_per_part]
            name = f"{keyword}.part{i + 1:0{width}d}.tsv"
            _atomic_write_stream(
                out_dir / name,
                _iter_part_bytes(header, (_data_line(h) for h in chunk), enc))
            parts_meta.append({"name": name, "rows": len(chunk)})

    manifest = {
        "schema_version": 1, "keyword": keyword, "encoding": enc,
        "total_rows": total, "data_sha256": data_sha,
        "tool_version": __version__,
        "max_rows_per_part": opts.max_rows_per_part,
        "items_per_mb": _ITEMS_PER_MB,
        "parts": parts_meta, "tool": "grep_analyzer", "spec_phase": "3",
    }
    if inputs_fingerprint is not None:            # resume の入力指紋照合用（H1）
        manifest["inputs_fingerprint"] = inputs_fingerprint
    _write_manifest(out_dir, keyword, manifest)   # manifest 原子確定
    _fsync_dir(out_dir)

    # manifest 確定後に孤児削除（有効出力を新出力出現前に破壊しない）。
    # 削除対象は旧 manifest が列挙した part 名のうち今回 keep に無いものだけ。
    # glob を使わないため別 keyword（"foo" と "foo.part5" 等）の出力を巻き込まない（H3）。
    keep = {p["name"] for p in parts_meta} | {f"{keyword}.manifest.json"}
    for name in sorted(prev_part_names - keep):
        try:
            (out_dir / name).unlink()
        except OSError:
            pass
