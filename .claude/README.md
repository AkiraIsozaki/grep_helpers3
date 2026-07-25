# .claude/ — Claude Code 開発基盤

このディレクトリは grep_analyzer の AI 支援開発基盤です。**skills / commands / agents の3層**で構成され、
spec-driven・superpowers・mattpocock-skills の3ソースを統合して作られています（設計の詳細と経緯は
[docs/claude-infra-design.md](../docs/claude-infra-design.md) を参照）。

```
.claude/
├── skills/      # 規律・知識（モデルが状況に応じて自動起動）
├── commands/    # /コマンド（ユーザーが起動するワークフローの入口）
├── agents/      # サブエージェント定義（隔離コンテキストで走る検証者）
└── settings.local.json
```

ルートの [CLAUDE.md](../CLAUDE.md) が毎セッション読み込まれ、「該当可能性が1%でもあるスキルは
応答より先に起動する」という起動規則とルーティング表を提供します。

## まず何をすればいいか

| やりたいこと | 入口 |
|---|---|
| 機能を追加したい | `/add-feature <機能名>`（設計承認 → 以降は自律ループ） |
| リファクタリングしたい | `/refactor <対象>` |
| プロジェクト文書を一式整備したい | `/setup-project` |
| 文書の品質を見てほしい | `/review-docs [パス]` |
| 普通に依頼する | そのまま書けば CLAUDE.md のルーティングで適切なスキルが自動起動 |

## skills 一覧（19本）

### プロジェクト規約 — このリポジトリの「法」
| スキル | 内容 |
|---|---|
| `coding-conventions` | 日本語コメント・命名規約・構造規約・実装の罠。コード作成/編集時に必ず適用 |
| `writing-tests` | テスト5層の縄張り・モックの線引き・日本語テスト名。テスト作成/修正時に必ず適用 |

### 開発規律 — 品質を守る鉄則（superpowers 由来）
| スキル | 鉄則 |
|---|---|
| `brainstorming` | 設計を提示しユーザー承認を得るまで実装しない（ハードゲート） |
| `test-driven-development` | 失敗するテストなしにプロダクションコードを書かない。先に書いたら削除 |
| `systematic-debugging` | 根本原因調査なしに修正しない。3回失敗したら停止して構造を疑う |
| `verification-before-completion` | 新鮮な検証エビデンスなしに完了を宣言しない |
| `requesting-code-review` | タスク完了・マージ前に code-reviewer エージェントへレビューを依頼 |
| `receiving-code-review` | 指摘は検証してから実装。迎合的同意（「おっしゃる通り!」）禁止 |

### ワークフロー運営
| スキル | 内容 |
|---|---|
| `steering` | 作業単位ごとの `.steering/YYYYMMDD-<トピック>/` 管理。tasklist.md が進捗の唯一の真実 |
| `dispatching-parallel-agents` | 独立タスク2件以上の並列サブエージェント運用 |
| `using-git-worktrees` | 隔離ワークスペースの確保（ネイティブツール優先） |
| `finishing-a-development-branch` | ブランチ完了時の4択（マージ/PR/保持/破棄）と後片付け |

### 文書作成 — スペック駆動開発（spec-driven 由来）
| スキル | 出力先 |
|---|---|
| `prd-writing` | docs/product-requirements.md |
| `functional-design` | docs/functional-design.md |
| `architecture-design` | docs/architecture.md |
| `repository-structure` | docs/repository-structure.md |
| `glossary-creation` | docs/glossary.md |

### 改善・メタ
| スキル | 内容 |
|---|---|
| `refactoring` | 9原則（可視性・不変性・プリミティブ執着解消 等）+ docs/ 同期を強制する原子サイクル |
| `writing-skills` | スキル自体の作成・編集。「スキル執筆はプロセス文書への TDD」 |

## commands 一覧（4本）

| コマンド | 流れ |
|---|---|
| `/setup-project` | docs/ideas/ の構想メモ → 文書5種を順に生成（PRD のみ人間承認） |
| `/add-feature <名前>` | brainstorming（承認ゲート）→ steering 計画 → TDD で tasklist 消化 → 検証 → 振り返り |
| `/refactor <対象>` | steering 計画 → 9原則分析 → 原子サイクル実行 → 検証 |
| `/review-docs [パス]` | doc-reviewer エージェントに委譲（メイン文脈を汚さない） |

## agents 一覧（3体）

| agent | 役割 | ツール |
|---|---|---|
| `code-reviewer` | 変更差分の2軸レビュー（Standards=規約準拠 / Spec=要求一致）、重大度付き | 読取 + git |
| `doc-reviewer` | 文書の5軸評価（完全性・明確性・一貫性・実装可能性・測定可能性） | 読取のみ |
| `implementation-validator` | 静的検証（層分離・可視性・docstring 形式・テスト縄張り）。コード不実行 | 読取 + grep |

## スキルを追加・編集するとき

1. `writing-skills` スキルを起動する（形式・記法・テスト方法が定義されている）
2. 形式は `skills/<name>/SKILL.md`。frontmatter は `name` / `description` のみ、description は
   「いつ使うか」を書く（内容の要約を書くと本文がスキップされる事故が起きる）
3. 全て日本語。他スキルへの参照はプレーン名（`` `steering` スキル``）。`@` リンク禁止
4. 追加したら CLAUDE.md のルーティング表と本 README を同期する

## 外部由来（このディレクトリ外）

`grill-me` / `grill-with-docs` は mattpocock/skills からユーザーレベルに導入済み
（[skills-lock.json](../skills-lock.json) 参照）。ここには重複配置していません。
