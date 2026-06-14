"""decode/言語判定の永続キャッシュ。値は (text, enc, replaced, language, dialect)。

キーに (abspath, mtime_ns, size, namespace) を含むため hop・worker・run を
またいで安全に共有でき、ソース変更時は自動でミスする。アーティファクトは
disk 上の 1 ファイル（1行 JSON ヘッダ ＋ 改行 ＋ 復号UTF-8本文）。
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path


class DecodeCache:
    def __init__(self, cache_dir: "Path | None", namespace: str = "") -> None:
        self._dir = Path(cache_dir) if cache_dir is not None \
            else Path(tempfile.mkdtemp(prefix="ga_decode_"))
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ns = namespace

    def _stat(self, abspath: str):
        try:
            st = os.stat(abspath)
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    def _artifact_path(self, abspath: str, sig) -> Path:
        mtime_ns, size = sig
        key = f"{self._ns}\0{abspath}\0{mtime_ns}\0{size}"
        h = hashlib.sha1(key.encode("utf-8", "surrogatepass")).hexdigest()
        return self._dir / f"{h}.dca"

    def get(self, abspath: str):
        sig = self._stat(abspath)
        if sig is None:
            return None
        path = self._artifact_path(abspath, sig)
        try:
            with open(path, encoding="utf-8") as f:
                header = f.readline()
                body = f.read()
        except OSError:
            return None
        try:
            meta = json.loads(header)
        except ValueError:
            return None
        if meta.get("mtime_ns") != sig[0] or meta.get("size") != sig[1]:
            return None
        return (body, meta["enc"], meta["replaced"],
                meta["language"], meta["dialect"])

    def put(self, abspath: str, meta) -> None:
        sig = self._stat(abspath)
        if sig is None:
            return
        text, enc, replaced, language, dialect = meta
        header = json.dumps({
            "enc": enc, "replaced": replaced, "language": language,
            "dialect": dialect, "mtime_ns": sig[0], "size": sig[1],
        }, ensure_ascii=False)
        path = self._artifact_path(abspath, sig)
        fd, tmp = tempfile.mkstemp(dir=str(self._dir), prefix="ga_dca_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(header + "\n")
                f.write(text)
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
