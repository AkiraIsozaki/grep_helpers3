"""M3: グローバル union に非 ASCII 記号が混じり全件走査へ落ちても、ASCII-only keyword の
decode_replaced 帰属は自前 prefilter で絞られ、逐次版（単独 run）と一致する。

旧実装は `union_keep is not None` を per-keyword 絞り込みの条件にしていたため、非 ASCII union
（global prefilter 無効）では全 keyword が FULL pass_results を受け、ASCII-only keyword が
他 keyword しか触れない replaced ファイルの decode_replaced を取り込んでいた。"""

import dataclasses

from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.pipeline import _default_opts, run


def _detail_lines(out_dir):
    diag = (out_dir / "diagnostics.txt").read_text("utf-8")
    body = diag.split("# detail", 1)[1] if "# detail" in diag else diag
    return body.splitlines()


def test_非ASCII_unionでもASCII_keywordのdecode_replacedは汚染されない(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    # AAA: ASCII シンボル ALPHACODE を chase
    (src / "A.java").write_text(
        "class A { static final int ALPHACODE=1; int r=ALPHACODE; }\n", "utf-8")
    # BBB: 非 ASCII シンボル ベータコード を chase（global union を非 ASCII にする）
    (src / "B.java").write_text(
        "class B { static final int ベータコード=1; int r=ベータコード; }\n", "utf-8")
    # Z: どちらの記号も含まない replaced=True ファイル（latin-1 replace を強制）
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
    # Z.java は非 ASCII keyword BBB だけが全件走査で触れる。ASCII keyword AAA は
    # 自前 prefilter（ALPHACODE）で Z.java を除外するので decode_replaced は 1 件だけ。
    # 旧実装は AAA も FULL を受けて 2 件になっていた。
    assert len(z_lines) == 1, z_lines
