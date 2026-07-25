# .claude/ — Claude Code 開発基盤

えー、こちらは grep_analyzer の長屋で働く AI 職人（Claude）の**仕込み部屋**でございます。
**skills / commands / agents の3層**でできておりまして、
spec-driven・superpowers・mattpocock-skills てえ三つの流儀を混ぜて仕立て直したもんだ。
普請の理屈と経緯を知りてえお方は [docs/claude-infra-design.md](../docs/claude-infra-design.md) を、
噺はいいから堅気の文で読みてえお方は
[docs/claude-infra-design-plain.md](../docs/claude-infra-design-plain.md) をご覧じろ。
上方の語りがお好みなら、代書屋仕立ての [README-daishoya.md](README-daishoya.md) てえ趣向もございます。

```
.claude/
├── skills/      # 心得 — 規律・知識（モデルが状況に応じて自動起動）
├── commands/    # 注文口 — /コマンド（ユーザーが起動するワークフローの入口）
├── agents/      # 検査役 — サブエージェント定義（隔離コンテキストで走る）
└── settings.local.json
```

壁の掟書き [CLAUDE.md](../CLAUDE.md) が毎セッション読み上げられて、
「該当の見込みが 1% でもあるスキルは返事より先に起動しろ」てえ決まりと案内板（ルーティング表）を配る寸法よ。

## まず何をすりゃいいんで

八っつぁん「ご隠居、能書きはいいから、どこを叩きゃ仕事が始まるんで」

ご隠居「せっかちだね。この表の通りだ」

| やりたいこと | 入口 |
|---|---|
| 機能を追加したい | `/add-feature <機能名>`（設計承認 → 以降は自律ループ） |
| リファクタリングしたい | `/refactor <対象>` |
| プロジェクト文書を一式整備したい | `/setup-project` |
| 文書の品質を見てほしい | `/review-docs [パス]` |
| 普通に頼みたい | そのまま書きゃあ、掟書きの案内板で適切なスキルが勝手に出てくる |

## skills 一覧（19本）

### プロジェクト規約 — この長屋の「家訓」だ。逆らうんじゃねえよ

| スキル | 内容 |
|---|---|
| `coding-conventions` | 日本語コメント・命名規約・構造規約・実装の罠。コード作成/編集時に必ず適用 |
| `writing-tests` | テスト5層の縄張り・モックの線引き・日本語テスト名。テスト作成/修正時に必ず適用 |

### 開発規律 — 職人の性根（superpowers 由来）。破りゃあ祟るよ

| スキル | 鉄則 |
|---|---|
| `brainstorming` | 設計を見せて旦那の判をもらうまで鑿は握らせねえ（ハードゲート） |
| `test-driven-development` | 失敗するテストなしにプロダクションコードを書くな。先に書いちまったら削除だ |
| `systematic-debugging` | 根本原因も調べずに直すな。三度しくじったら手を止めて骨組みを疑え |
| `verification-before-completion` | 新鮮な検証エビデンスなしに「できやした」と言うんじゃねえ |
| `requesting-code-review` | タスク完了・マージ前にゃ code-reviewer に検分を頼め |
| `receiving-code-review` | 指摘は検証してから直せ。「おっしゃる通りで!」なんて太鼓持ちは御法度 |

### ワークフロー運営 — 普請場の段取りだ

| スキル | 内容 |
|---|---|
| `steering` | 作業単位ごとの `.steering/YYYYMMDD-<トピック>/` 管理。tasklist.md が進捗の唯一の真実 |
| `dispatching-parallel-agents` | 独立タスク2件以上の並列サブエージェント運用 |
| `using-git-worktrees` | 隔離ワークスペースの確保（ネイティブツール優先） |
| `finishing-a-development-branch` | ブランチ完了時の4択（マージ/PR/保持/破棄）と後片付け |

### 文書作成 — スペック駆動開発（spec-driven 由来）。図面なしの普請は請けねえ

| スキル | 出力先 |
|---|---|
| `prd-writing` | docs/product-requirements.md |
| `functional-design` | docs/functional-design.md |
| `architecture-design` | docs/architecture.md |
| `repository-structure` | docs/repository-structure.md |
| `glossary-creation` | docs/glossary.md |

### 改善・メタ — 道具の手入れも仕事のうちだ

| スキル | 内容 |
|---|---|
| `refactoring` | 9原則（可視性・不変性・プリミティブ執着解消 等）+ docs/ 同期を強制する原子サイクル |
| `writing-skills` | スキル自体の作成・編集。「スキル執筆はプロセス文書への TDD」てえ心得だ |

## commands 一覧（4本）

| コマンド | 流れ |
|---|---|
| `/setup-project` | docs/ideas/ の構想メモ → 文書5種を順に生成（PRD のみ人間承認） |
| `/add-feature <名前>` | brainstorming（承認ゲート）→ steering 計画 → TDD で tasklist 消化 → 検証 → 振り返り |
| `/refactor <対象>` | steering 計画 → 9原則分析 → 原子サイクル実行 → 検証 |
| `/review-docs [パス]` | doc-reviewer に委譲（メインの座敷を汚さねえ） |

## agents 一覧（3体）

手前の仕事を手前で褒める目利きは信用ならねえ、てんで検分は離れ座敷でやらせます。

| agent | 役割 | ツール |
|---|---|---|
| `code-reviewer` | 変更差分の2軸レビュー（Standards=規約準拠 / Spec=要求一致）、重大度付き | 読取 + git |
| `doc-reviewer` | 文書の5軸評価（完全性・明確性・一貫性・実装可能性・測定可能性） | 読取のみ |
| `implementation-validator` | 静的検証（層分離・可視性・docstring 形式・テスト縄張り）。コードは実行しねえ | 読取 + grep |

## スキルを増やす・手を入れるときの心得

1. まず `writing-skills` スキルを起動しな（形式・記法・検分のやり方が書いてある）
2. 形式は `skills/<name>/SKILL.md`。frontmatter は `name` / `description` のみ。description にゃ
   「いつ使うか」だけ書け（内容を要約してみろ、看板だけ読まれて中身が素通りされる事故が起きる）
3. 全て日本語だ。他スキルへの参照はプレーン名（`` `steering` スキル``）。`@` リンクは御法度
4. 増やしたら CLAUDE.md の案内板と本 README を揃えろ。案内板の古い長屋は道に迷うよ

## 外部由来（この部屋の外の話）

`grill-me` / `grill-with-docs` は mattpocock/skills からユーザーレベルに導入済みだ
（[skills-lock.json](../skills-lock.json) をご覧じろ）。同じ名の職人を二人並べる法はねえ、
ここには置いておりません。
