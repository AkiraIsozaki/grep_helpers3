"""lock-step 共有エンジン run_fixedpoint_multi の単一keyword同値テスト（Phase4 Task3）。

単一 keyword の multi パスは逐次版 run_fixedpoint と byte 同値でなければならない
（spec §4.1）。golden(92) byte 不変の最小単位検証。
"""

# §6.2＝§8.4 走査構造依存・全件性対象外（rev.2 C-2連鎖で確定した固定の除外集合）。
# lock-step の diagnostics detail/件数が逐次版併合と一致する保証から外れる唯一のカテゴリ。
EXCLUDED_FROM_PARITY = frozenset({"automaton_split", "graph_spilled"})


def test_multiは単一keywordで逐次版とindirect一致(tmp_path):
    from grep_analyzer.pipeline import _default_opts
    from grep_analyzer.fixedpoint import run_fixedpoint
    from grep_analyzer.fixedpoint._lockstep import run_fixedpoint_multi
    from grep_analyzer.fixedpoint._seed import initialize_state
    from grep_analyzer.diagnostics import Diagnostics
    from grep_analyzer.walk import collect_files
    from grep_analyzer.model import Hit
    src = tmp_path
    (src / "A.java").write_text(
        "class A { static final int KCODE=1; int r=KCODE; }\n", "utf-8")
    opts = _default_opts()
    seed = [Hit(keyword="K", language="java", file="A.java", lineno=1,
                ref_kind="direct", category="定義", category_sub="",
                usage_summary="", via_symbol="", chain="", snippet="",
                encoding="utf-8", confidence="high")]
    files = collect_files(src, include=[], exclude=[], follow_symlinks=False,
                          max_file_bytes=5_000_000, diag=Diagnostics())
    st1 = initialize_state(seed, src, opts, Diagnostics())
    seq = run_fixedpoint(seed, src, opts, st1.diagnostics, files=files)
    st2 = initialize_state(seed, src, opts, Diagnostics())
    multi = run_fixedpoint_multi({"K": st2}, src, opts, files=files,
                                 unsafe_rels=set(), enc_memo=None)["K"]
    assert [h.chain for h in seq] == [h.chain for h in multi]
    assert [h.file for h in seq] == [h.file for h in multi]


def test_単一keywordの走査済み非ヒットreplacedファイルのdecode_replacedが保たれる(tmp_path):
    """走査されたが symbol 非ヒットの replaced=True ファイルの decode_replaced 診断が
    lockstep 単一 keyword 経路で逐次版と byte 同値に保たれる回帰ロック（FIX 1）。

    rev.2 C-2 の「any found」絞り込みはこの relpath を pass_results から落とすため
    decode_replaced を欠落させた（golden 92 が見逃すケース）。FULL pass_results を
    absorb へ渡す修正で復活する。
    """
    import dataclasses
    from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
    from grep_analyzer.pipeline import _default_opts, run

    src = tmp_path / "src"
    src.mkdir()
    # hit file: seed の KCODE を含み chase を生む
    (src / "A.java").write_text(
        "class A { static final int KCODE=1; int r=KCODE; }\n", "utf-8")
    # no-hit file: latin-1 replace を強制する生バイト＋chase 記号を一切含まない
    b_bytes = "class Zqxj {}\n".encode("utf-8") + b"// \x80\x81\x82\x83\xfd\xfe\xff\n"
    (src / "B.java").write_bytes(b_bytes)
    # 前提検証: B.java は replaced=True で復号される
    _, _, replaced = decode_bytes(b_bytes, DEFAULT_FALLBACK)
    assert replaced, "前提崩れ: B.java が replaced=True で復号されない"

    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "KCODE.grep").write_text(
        "A.java:1:class A { static final int KCODE=1; int r=KCODE; }\n", "utf-8")

    # use_ripgrep=False ＝ B.java を必ず走査対象に残す（prefilter で脱落させない）
    out = tmp_path / "o"
    opts = dataclasses.replace(_default_opts(), jobs=1, use_ripgrep=False)
    rc = run(input_dir=inp, output_dir=out, source_root=src, opts=opts)
    assert rc == 0
    diag = (out / "diagnostics.txt").read_text("utf-8")
    detail = diag.split("# detail", 1)[1] if "# detail" in diag else diag
    assert any(ln.startswith("decode_replaced\t") and "B.java" in ln
               for ln in detail.splitlines()), \
        "走査済み・symbol 非ヒットの replaced ファイルの decode_replaced が欠落"


def test_pipeline_lockstepは複数keywordで各TSV逐次版一致(tmp_path):
    """複数 keyword の lock-step 出力が逐次版（各 keyword 単独 run）と byte 同値であり、
    かつ indirect 経路を実際に駆動することを検証する（Phase4 U3 レビュー反映）。

    コーパスは両 keyword が SHARED シンボル（ALPHA/BETA 両定数を宣言する Const.java:1）を
    seed し、OVERLAPPING ファイル（UseA/UseB）へ chase する形にしてある:
    - ALPHA は ALPHA/BETA を chase → UseA(ALPHA) と UseB(BETA) に hit
    - BETA も ALPHA/BETA を chase → UseA(ALPHA) と UseB(BETA) に hit
    これにより run_fixedpoint_multi の hop ループ本体（union 走査・cross-keyword chase・
    per-keyword absorb）が実走する。旧コーパス（K1=1/K2=2 の int リテラル）は indirect が
    一切出ず、ループ本体を一度も実行しなかった（lockstep エンジン未検証）。
    """
    from grep_analyzer.pipeline import run, _default_opts
    src = tmp_path / "src"; src.mkdir()
    (src / "Const.java").write_text(
        "class Const { public static final int ALPHA = 1; public static final int BETA = 2; }\n", "utf-8")
    (src / "UseA.java").write_text("class UseA { int x = Const.ALPHA; }\n", "utf-8")
    (src / "UseB.java").write_text("class UseB { int y = Const.BETA; }\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "ALPHA.grep").write_text("Const.java:1:    public static final int ALPHA = 1;\n", "utf-8")
    (inp / "BETA.grep").write_text("Const.java:1:    public static final int BETA = 2;\n", "utf-8")
    out_new = tmp_path / "new"; run(inp, out_new, src, _default_opts())
    out_seq = tmp_path / "seq"
    for kw in ("ALPHA", "BETA"):
        sub = tmp_path / f"in_{kw}"; sub.mkdir()
        (sub / f"{kw}.grep").write_text((inp / f"{kw}.grep").read_text("utf-8"), "utf-8")
        run(sub, out_seq, src, _default_opts())
    alpha_new = (out_new / "ALPHA.tsv").read_bytes()
    beta_new = (out_new / "BETA.tsv").read_bytes()
    assert alpha_new == (out_seq / "ALPHA.tsv").read_bytes()
    assert beta_new == (out_seq / "BETA.tsv").read_bytes()
    # lockstep ループ本体が実走したことの保証: 各 TSV に indirect 行（chain は ` -> ` を含む）が
    # 存在する。将来 zero-indirect なコーパスに退行しても silently pass しないようロックする。
    assert b"indirect:" in alpha_new and b" -> " in alpha_new, \
        "ALPHA.tsv に indirect 行が無い（lockstep ループ本体が実走していない）"
    assert b"indirect:" in beta_new and b" -> " in beta_new, \
        "BETA.tsv に indirect 行が無い（lockstep ループ本体が実走していない）"


def test_複数keywordはjobs1とjobs2でバイト同値(tmp_path):
    """複数 keyword を jobs=1 と jobs=2 で run した各 keyword の .tsv がバイト同値（C1）。

    cross-keyword lock-step の並列経路（run_fixedpoint_multi・jobs>1）の決定性を固定する。
    コーパスは MAX_RETRY/MAX_TIMEOUT が共有ソース Config.java を seed し、
    Service.java → Client.java の 2hop チェーンを形成する（cross-keyword union 走査を駆動）。
    """
    import dataclasses
    from grep_analyzer.pipeline import run, _default_opts

    src = tmp_path / "src"; src.mkdir()
    (src / "Config.java").write_text(
        "class Config {\n"
        "    public static final int MAX_RETRY = 3;\n"
        "    public static final int MAX_TIMEOUT = 30;\n"
        "}\n", "utf-8")
    (src / "Service.java").write_text(
        "class Service {\n"
        "    static final int RETRY_LIMIT = Config.MAX_RETRY;\n"
        "    static final int TIMEOUT = Config.MAX_TIMEOUT;\n"
        "}\n", "utf-8")
    (src / "Client.java").write_text(
        "class Client {\n"
        "    void connect() {\n"
        "        int r = Service.RETRY_LIMIT;\n"
        "        int t = Service.TIMEOUT;\n"
        "    }\n"
        "}\n", "utf-8")

    inp = tmp_path / "in"; inp.mkdir()
    (inp / "MAX_RETRY.grep").write_text(
        "Config.java:2:    public static final int MAX_RETRY = 3;\n", "utf-8")
    (inp / "MAX_TIMEOUT.grep").write_text(
        "Config.java:3:    public static final int MAX_TIMEOUT = 30;\n", "utf-8")

    opts1 = dataclasses.replace(_default_opts(), jobs=1, use_ripgrep=False)
    opts2 = dataclasses.replace(_default_opts(), jobs=2, use_ripgrep=False)

    out1 = tmp_path / "o1"
    assert run(inp, out1, src, opts1) == 0
    out2 = tmp_path / "o2"
    assert run(inp, out2, src, opts2) == 0

    for name in ("MAX_RETRY.tsv", "MAX_TIMEOUT.tsv"):
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes(), \
            f"jobs=1 と jobs=2 で {name} がバイト不一致（並列決定性バグ）"

    # lockstep ループ本体が実走したこと（cross-keyword union 走査の保証）。
    retry_bytes = (out1 / "MAX_RETRY.tsv").read_bytes()
    timeout_bytes = (out1 / "MAX_TIMEOUT.tsv").read_bytes()
    assert b"indirect:" in retry_bytes and b" -> " in retry_bytes, \
        "MAX_RETRY.tsv に indirect 行が無い（lockstep ループ本体が実走していない）"
    assert b"indirect:" in timeout_bytes and b" -> " in timeout_bytes, \
        "MAX_TIMEOUT.tsv に indirect 行が無い（lockstep ループ本体が実走していない）"


def test_pipeline_lockstep_resume済keywordは再finalizeされない(tmp_path):
    """opts.resume=True で完了済 keyword は再 finalize されず（mtime 不変）、
    resume_skipped 診断が出る。他 keyword は通常処理される。"""
    import dataclasses
    from grep_analyzer.pipeline import run, _default_opts
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text(
        "class A { static final int K1=1; int a=K1; static final int K2=2; int b=K2; }\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "K1.grep").write_text("A.java:1:    static final int K1=1;\n", "utf-8")
    (inp / "K2.grep").write_text("A.java:1:    static final int K2=2;\n", "utf-8")
    out = tmp_path / "o"
    # 1回目: 通常 run で K1/K2 両方の完了出力（manifest 含む）を生成。
    run(inp, out, src, _default_opts())
    from grep_analyzer import resume
    resume_opts = dataclasses.replace(_default_opts(), resume=True)
    assert resume.is_complete(out, "K1", resume_opts), "前提崩れ: K1 が完了判定されない"
    # K1 の TSV mtime を記録 → resume run 後に不変であること（再 finalize 無し）を確認。
    k1_path = out / "K1.tsv"
    k1_mtime = k1_path.stat().st_mtime_ns
    # K2 を再処理させるため manifest を消す（未完了化）。
    (out / "K2.manifest.json").unlink()
    # 2回目: resume=True。K1 はスキップ、K2 は再処理。
    run(inp, out, src, resume_opts)
    assert k1_path.stat().st_mtime_ns == k1_mtime, "K1 が再 finalize された（resume スキップ失敗）"
    diag = (out / "diagnostics.txt").read_text("utf-8")
    assert any(ln == "resume_skipped\tK1" for ln in diag.splitlines()), \
        "resume_skipped 診断に K1 が無い"
    assert (out / "K2.tsv").read_bytes(), "K2 が再処理されていない"


def test_automaton_splitはlive記号を持つkwのみに付与(tmp_path):
    """B1: nchunks>1 時に live 記号(sc|stm)がゼロの keyword には automaton_split を付与しない。

    コーパス設計:
    - KW1 (ALPHA): Const.java → MidA.java/MidB.java(MIDA/MIDB/MIDC/MIDD) → LeafA.java と
      2 hop chase する。hop2 で 4 シンボルが live → force_chunks=3 で nchunks=3 が誘発される。
    - KW2 (BETA): Const.java を seed にするが BETA を参照する定数は存在しない。
      hop1 では BETA が live だが hop2 では chase_active/terminal_active が空
      → hop2 の walk では KW2 の sc|stm がゼロ。

    修正前（バグ）: hop2 で nchunks>1 のとき、live ゼロの BETA にも automaton_split が入る。
    修正後（正常）: hop2 の automaton_split は ALPHA だけに付与される。
    """
    import dataclasses
    from grep_analyzer.pipeline import _default_opts
    from grep_analyzer.fixedpoint._lockstep import run_fixedpoint_multi
    from grep_analyzer.fixedpoint._seed import initialize_state
    from grep_analyzer.diagnostics import Diagnostics
    from grep_analyzer.walk import collect_files
    from grep_analyzer.model import Hit

    src = tmp_path / "src"; src.mkdir()
    # KW1 (ALPHA): hop1 で 4 定数(MIDA/MIDB/MIDC/MIDD)を発見し hop2 まで chase する。
    (src / "Const.java").write_text(
        "class Const {\n"
        "    public static final int ALPHA = 1;\n"
        "    public static final int BETA = 2;\n"
        "}\n", "utf-8")
    # hop1: ALPHA を参照して 4 定数を定義 → hop2 で 4 live symbols
    (src / "MidA.java").write_text(
        "class MidA {\n"
        "    public static final int MIDA = Const.ALPHA;\n"
        "    public static final int MIDB = Const.ALPHA;\n"
        "}\n", "utf-8")
    (src / "MidB.java").write_text(
        "class MidB {\n"
        "    public static final int MIDC = Const.ALPHA;\n"
        "    public static final int MIDD = Const.ALPHA;\n"
        "}\n", "utf-8")
    # hop2: 4 定数の参照 (ALPHA の chase がここまで届く)
    (src / "LeafA.java").write_text(
        "class LeafA { int a = MidA.MIDA; int b = MidA.MIDB;"
        " int c = MidB.MIDC; int d = MidB.MIDD; }\n", "utf-8")
    # KW2 (BETA): BETA を参照する定数定義は存在しない → hop1 で chase が終わる

    opts = dataclasses.replace(
        _default_opts(), jobs=1, use_ripgrep=False, force_chunks=3, max_passes=3)

    files = collect_files(src, include=[], exclude=[], follow_symlinks=False,
                         max_file_bytes=5_000_000, diag=Diagnostics())

    def make_hit(kw, file, lineno, snippet):
        return Hit(keyword=kw, language="java", file=file, lineno=lineno,
                   ref_kind="direct", category="定義", category_sub="",
                   usage_summary="", via_symbol="", chain="", snippet=snippet,
                   encoding="utf-8", confidence="high")

    alpha_seed = [make_hit("ALPHA", "Const.java", 2,
                           "    public static final int ALPHA = 1;")]
    beta_seed  = [make_hit("BETA",  "Const.java", 3,
                           "    public static final int BETA = 2;")]

    diag_alpha = Diagnostics()
    diag_beta  = Diagnostics()
    st_alpha = initialize_state(alpha_seed, src, opts, diag_alpha)
    st_beta  = initialize_state(beta_seed,  src, opts, diag_beta)

    run_fixedpoint_multi(
        {"ALPHA": st_alpha, "BETA": st_beta}, src, opts, files=files,
        unsafe_rels=set(), enc_memo=None)

    alpha_splits = diag_alpha._detail.get("automaton_split", [])
    beta_splits  = diag_beta._detail.get("automaton_split", [])

    # 前提確認: ALPHA は hop2 で 4 symbols が live かつ nchunks=3(>1) → hop2 の split が発生
    assert len(alpha_splits) >= 2, (
        f"前提崩れ: ALPHA が 2 hop 以上 automaton_split を持たない（{alpha_splits}）。"
        "コーパスが hop2 まで chase していないか nchunks>1 が誘発されていない。")

    # 前提確認: hop1 では BETA も live(sc={'BETA'}) → hop1 の automaton_split は BETA にも入る
    assert any("hop=1" in s for s in beta_splits), (
        f"前提崩れ: BETA の hop1 automaton_split が無い（{beta_splits}）。"
        "hop1 では BETA が live 記号を持つため付与されるべき。")

    # B1 の核心: hop2 では BETA は live 記号ゼロ → hop2 の automaton_split は BETA に入らない。
    # 修正前（バグ）: BETA に hop=2 の automaton_split が入る（無差別付与）。
    # 修正後（正常）: BETA は hop=1 のみ（hop=2 は live ゼロゆえ付与なし）。
    beta_hop2_splits = [s for s in beta_splits if "hop=2" in s]
    assert beta_hop2_splits == [], (
        f"B1 バグ: live 記号ゼロの BETA に hop=2 の automaton_split が付与されている。"
        f"BETA splits={beta_splits}")


def _parse_diagnostics(text):
    """diagnostics.txt を (summary: dict[cat,int], detail: dict[cat,list[str]]) に分解する。

    render 形式は `# summary` 区画にカテゴリ別件数（`cat\\tN`）、`# detail` 区画に
    `cat\\tmessage`（message 自体に \\t を含むことがある＝最初の \\t のみで分割）。
    """
    summary: dict[str, int] = {}
    detail: dict[str, list[str]] = {}
    section = None
    for ln in text.splitlines():
        if ln == "# summary":
            section = "summary"
            continue
        if ln == "# detail":
            section = "detail"
            continue
        if not ln:
            continue
        cat, _, msg = ln.partition("\t")
        if section == "summary":
            summary[cat] = int(msg)
        elif section == "detail":
            detail.setdefault(cat, []).append(msg)
    return summary, detail


def test_lockstep_diagnostics順序が逐次版と一致_除外automaton_split_graph_spilled(tmp_path):
    """lock-step diagnostics.txt のカテゴリ別 detail 順・SUMMARY 件数が、各 keyword を
    単独 run した逐次版を sorted keyword 順に併合したものと一致する（Phase4 Task5）。

    §6.2＝§8.4 走査構造依存・全件性対象外の `automaton_split` と `graph_spilled` のみ
    比較対象から除外する（rev.2 C-2連鎖で確定した固定の除外集合）:
    - automaton_split は GLOBAL hop ごとに全 keyword の diag へ1回ずつ発火するため、
      逐次版の per-keyword 発火（keyword ごとの local hop で個別発火）とは detail も件数も
      構造的に異なる。
    - graph_spilled の `hop={hop}` は lock-step では global hop 番号、逐次版では local hop
      番号であり一致しない。
    これら走査構造に依存する2カテゴリ以外（decode_replaced / symbol_rejected /
    missing_source / bad_grep_line 等）は merge_in_order により逐次版と byte 一致しなければ
    ならない（pipeline.py §6 の併合が逐次版の単一 diag 追記順を再現する保証のロック）。

    本コーパスが実際に産出する非除外カテゴリ:
      bad_grep_line / decode_replaced / missing_source / symbol_rejected。
    """
    import dataclasses
    from grep_analyzer.pipeline import run, _default_opts
    from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes

    src = tmp_path / "src"; src.mkdir()
    # ALPHA 定数定義（chase の起点）。同じ行に short var x を置き symbol_rejected(too_short) を誘発。
    (src / "Const.java").write_text(
        "class Const { public static final int ALPHA = 1; int x; }\n", "utf-8")
    # ALPHA を参照しつつ short var v/q を導入（symbol_rejected を更に発生させる）。
    (src / "UseA.java").write_text(
        "class UseA { int v = Const.ALPHA; int q = x; }\n", "utf-8")
    # chase 中に走査されるが symbol 非ヒットの replaced=True ファイル → decode_replaced。
    bad_bytes = "class Zz { int ALPHA; }\n".encode("utf-8") + b"// \x80\x81\xff\n"
    (src / "Bad.java").write_bytes(bad_bytes)
    _, _, replaced = decode_bytes(bad_bytes, DEFAULT_FALLBACK)
    assert replaced, "前提崩れ: Bad.java が replaced=True で復号されない"

    inp = tmp_path / "in"; inp.mkdir()
    # ALPHA.grep: 正常行＋欠落ソース行(missing_source)＋コロン無し行(bad_grep_line)。
    (inp / "ALPHA.grep").write_text(
        "Const.java:1:    public static final int ALPHA = 1;\n"
        "MISSING.java:5:something here\n"
        "garbage line no colon\n", "utf-8")
    (inp / "BETA.grep").write_text(
        "Const.java:1:    public static final int ALPHA = 1;\n", "utf-8")

    # use_ripgrep=False ＝テスト対象の OFF 経路（prefilter で relpath を脱落させない）。
    opts = dataclasses.replace(_default_opts(), jobs=1, use_ripgrep=False)

    out_new = tmp_path / "new"
    assert run(inp, out_new, src, opts) == 0
    ls_summary, ls_detail = _parse_diagnostics(
        (out_new / "diagnostics.txt").read_text("utf-8"))

    # 逐次版相当: 各 keyword を単独入力 dir で run し、sorted keyword 順に併合。
    seq_summary: dict[str, int] = {}
    seq_detail: dict[str, list[str]] = {}
    for kw in sorted(("ALPHA", "BETA")):
        sub = tmp_path / f"in_{kw}"; sub.mkdir()
        (sub / f"{kw}.grep").write_text((inp / f"{kw}.grep").read_text("utf-8"), "utf-8")
        out_kw = tmp_path / f"seq_{kw}"
        assert run(sub, out_kw, src, opts) == 0
        s, d = _parse_diagnostics((out_kw / "diagnostics.txt").read_text("utf-8"))
        for c, n in s.items():
            seq_summary[c] = seq_summary.get(c, 0) + n
        for c, msgs in d.items():
            seq_detail.setdefault(c, []).extend(msgs)

    # 本テストが意図したカバレッジ（コーパスが退行して空にならないことのロック）。
    produced = set(ls_detail) - EXCLUDED_FROM_PARITY
    assert {"bad_grep_line", "decode_replaced", "missing_source",
            "symbol_rejected"} <= produced, \
        f"コーパスが想定カテゴリを産出していない: {sorted(produced)}"

    # 非除外カテゴリの DETAIL 順が逐次版併合と完全一致すること。
    for cat in sorted((set(ls_detail) | set(seq_detail)) - EXCLUDED_FROM_PARITY):
        assert ls_detail.get(cat, []) == seq_detail.get(cat, []), (
            f"非除外カテゴリ {cat} の detail が逐次版と不一致:\n"
            f"  lock-step={ls_detail.get(cat, [])}\n"
            f"  sequential={seq_detail.get(cat, [])}")

    # 非除外カテゴリの SUMMARY 件数も一致すること。
    for cat in sorted((set(ls_summary) | set(seq_summary)) - EXCLUDED_FROM_PARITY):
        assert ls_summary.get(cat, 0) == seq_summary.get(cat, 0), (
            f"非除外カテゴリ {cat} の summary 件数が不一致: "
            f"lock-step={ls_summary.get(cat, 0)} sequential={seq_summary.get(cat, 0)}")


def test_lockstep_scan_hopはglobal_hop回のみ呼ばれ走査が圧縮される(tmp_path):
    """lock-step は scan_hop を GLOBAL hop ごとに1回だけ呼び、逐次版の Σ(per-keyword hop)
    より厳密に少ない回数で走査する（Phase4 Task6 走査圧縮・C3 マジック値排除）。

    コーパスは 2 keyword × 各2 hop を要するよう構成: 各 keyword は ALPHA/BETA を seed し
    （Const.java:1 が両定数を宣言）、hop1 で MidA(MIDA)/MidB(MIDB) を発見、hop2 で
    LeafA/LeafB へ chase が届く。lock-step の global hop は 2 だが、逐次版は 2 keyword ×
    2 hop = 4 回 scan_hop を呼ぶ（実測値として検証）。
    """
    import dataclasses
    from grep_analyzer.pipeline import run, _default_opts
    import grep_analyzer.fixedpoint._lockstep as lockstep_mod

    src = tmp_path / "src"; src.mkdir()
    (src / "Const.java").write_text(
        "class Const { public static final int ALPHA = 1; "
        "public static final int BETA = 2; }\n", "utf-8")
    # hop1: ALPHA/BETA を参照しつつ新定数 MIDA/MIDB を定義 → 次 hop の chase 源。
    (src / "MidA.java").write_text(
        "class MidA { public static final int MIDA = Const.ALPHA; }\n", "utf-8")
    (src / "MidB.java").write_text(
        "class MidB { public static final int MIDB = Const.BETA; }\n", "utf-8")
    # hop2: MIDA/MIDB の利用箇所（chase がここまで届く＝各 keyword ≥2 hop を保証）。
    (src / "LeafA.java").write_text("class LeafA { int z = MidA.MIDA; }\n", "utf-8")
    (src / "LeafB.java").write_text("class LeafB { int z = MidB.MIDB; }\n", "utf-8")

    inp = tmp_path / "in"; inp.mkdir()
    (inp / "ALPHA.grep").write_text(
        "Const.java:1:    public static final int ALPHA = 1;\n", "utf-8")
    (inp / "BETA.grep").write_text(
        "Const.java:1:    public static final int BETA = 2;\n", "utf-8")
    opts = dataclasses.replace(_default_opts(), jobs=1, use_ripgrep=False)

    # _lockstep が import 済みの scan_hop を計数ラッパに差し替える。
    orig_scan_hop = lockstep_mod.scan_hop
    calls = {"n": 0}

    def counting_scan_hop(*args, **kwargs):
        calls["n"] += 1
        return orig_scan_hop(*args, **kwargs)

    lockstep_mod.scan_hop = counting_scan_hop
    try:
        out = tmp_path / "o"
        assert run(inp, out, src, opts) == 0
        multi_count = calls["n"]

        # 逐次版合計を実測: 各 keyword を単独 input dir で pipeline.run() して合算。
        seq_sum = 0
        for kw in ("ALPHA", "BETA"):
            sub = tmp_path / f"in_{kw}"; sub.mkdir(exist_ok=True)
            (sub / f"{kw}.grep").write_text(
                (inp / f"{kw}.grep").read_text("utf-8"), "utf-8")
            calls["n"] = 0
            run(sub, tmp_path / f"seq_{kw}", src, opts)
            seq_sum += calls["n"]
    finally:
        lockstep_mod.scan_hop = orig_scan_hop

    # コーパスが実際に多段 chase を駆動したこと（hop2 シンボル MIDA/MIDB に到達）。
    alpha_tsv = (out / "ALPHA.tsv").read_text("utf-8")
    beta_tsv = (out / "BETA.tsv").read_text("utf-8")
    assert "MIDA" in alpha_tsv and "MIDB" in beta_tsv, \
        "コーパスが hop2 まで chase していない（走査圧縮テストが無意味化）"

    # 逐次版が実際に複数 hop を踏んでいることを確認（圧縮前提の保証）。
    assert seq_sum > multi_count, \
        (f"逐次版合計 {seq_sum} が lock-step {multi_count} 以下 — "
         f"コーパスが lock-step の圧縮効果を駆動していない")

    # 走査圧縮: lock-step の scan_hop 呼出は逐次版合計より厳密に少ない（マジック値なし）。
    assert multi_count < seq_sum, \
        f"走査が圧縮されていない: lock-step={multi_count} >= 逐次版Σhop={seq_sum}"
