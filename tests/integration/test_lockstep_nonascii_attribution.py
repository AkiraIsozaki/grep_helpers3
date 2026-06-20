"""非 ASCII union（全件走査）時の decode_replaced 帰属に関する受容済み制限の characterization。

検討経緯（M3）: 非 ASCII union では global prefilter が無効化（union_keep=None）され、
ASCII-only keyword の per-keyword 絞り込みも行わないため、その keyword は自分が触れない
replaced ファイルの decode_replaced 診断を取り込む（逐次版より多い）。

一度は per-keyword prefilter を union_keep 非依存にして帰属を逐次版へ揃えたが、それは
ASCII keyword ごとに毎 hop フルコーパス rg を spawn し、SJIS で日本語識別子を追う本ツールの
主用途（60GB・多 keyword・多 hop）で走査が爆発する重大な性能退行だった。得られるのは
decode_replaced 診断の帰属精度のみ（TSV は不変・perkw_diag gated）。性能を優先し、この
診断専用の帰属差は既知の受容済み制限とする。本テストはその決定を固定する（無断で
高コスト版に戻したら気づけるように）。"""

import dataclasses

from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.pipeline import _default_opts, run


def _detail_lines(out_dir):
    diag = (out_dir / "diagnostics.txt").read_text("utf-8")
    body = diag.split("# detail", 1)[1] if "# detail" in diag else diag
    return body.splitlines()


def test_非ASCII_union時のdecode_replaced帰属は性能優先でFULLのまま許容する(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "A.java").write_text(
        "class A { static final int ALPHACODE=1; int r=ALPHACODE; }\n", "utf-8")
    (src / "B.java").write_text(
        "class B { static final int ベータコード=1; int r=ベータコード; }\n", "utf-8")
    z_bytes = "class Zqxj {}\n".encode("utf-8") + b"// \x80\x81\x82\x83\xfd\xfe\xff\n"
    (src / "Z.java").write_bytes(z_bytes)
    _, _, replaced = decode_bytes(z_bytes, DEFAULT_FALLBACK)
    assert replaced, "前提崩れ: Z.java が replaced=True で復号されない"

    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "AAA.grep").write_text(
        "A.java:1:class A { static final int ALPHACODE=1; int r=ALPHACODE; }\n", "utf-8")
    (inp / "BBB.grep").write_text(
        "B.java:1:class B { static final int ベータコード=1; int r=ベータコード; }\n", "utf-8")

    out = tmp_path / "o"
    opts = dataclasses.replace(_default_opts(), jobs=1, use_ripgrep=True)
    assert run(input_dir=inp, output_dir=out, source_root=src, opts=opts) == 0

    z_lines = [ln for ln in _detail_lines(out)
               if ln.startswith("decode_replaced\t") and "Z.java" in ln]
    # 非 ASCII union → 全件走査。両 keyword が FULL pass_results を受けるため Z.java の
    # decode_replaced は 2 件（AAA/BBB 双方）になる。これは性能優先で受容した既知の帰属差。
    # 高コスト版（union_keep 非依存 per-keyword prefilter）に戻すと 1 件になる。
    assert len(z_lines) == 2, z_lines
