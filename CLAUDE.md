# grep_analyzer

grep 出力を解析するオフライン CLI ツール（Python 3.12 / `src/grep_analyzer/` / pytest）。

- テスト実行: `python -m pytest tests/ -q --tb=line`
- コミット: 日本語 Conventional Commits（例: `fix(classify): ...`）。
- 文書の2層構造: `docs/` = 永続仕様（北極星）、`.steering/YYYYMMDD-<トピック>/` = 作業単位の計画・tasklist・振り返り（`steering` スキルが管理）。`docs/superpowers/{specs,plans}/` は旧運用の遺産（読み取り専用の歴史）。

## スキル起動規則（最重要）

**該当する可能性が1%でもあるスキルは、応答（明確化の質問を含む）より先に起動する。**
起動時は「[スキル名] を使用します」と宣言し、スキルにチェックリストがあれば項目毎に todo 化する。

優先順位: ユーザーの直接指示 > 本ファイル > スキル > 既定動作。
ディスパッチされたサブエージェントはこの規則の対象外（与えられた指示のみに従う）。

## ルーティング表

| 状況 | スキル |
|---|---|
| 機能追加・挙動変更・「〜を作って」 | `brainstorming`（設計承認まで実装禁止）→ `steering` |
| 作業計画・tasklist 運用・振り返り | `steering` |
| コードを書く（全般） | `coding-conventions` |
| テストを書く・直す | `writing-tests` + `test-driven-development` |
| バグ・テスト失敗・想定外の挙動 | `systematic-debugging`（根本原因調査が先） |
| リファクタリング・設計改善 | `refactoring` |
| 完了・修正済み・成功を宣言する直前 | `verification-before-completion` |
| タスク完了時・マージ前のレビュー依頼 | `requesting-code-review` |
| レビュー指摘を受けたとき | `receiving-code-review` |
| 独立タスク2件以上の並列処理 | `dispatching-parallel-agents` |
| ブランチ作業の完了処理 | `finishing-a-development-branch` |
| 隔離された作業環境が必要 | `using-git-worktrees` |
| PRD・機能設計・アーキテクチャ・リポジトリ構造・用語集の文書作成 | `prd-writing` / `functional-design` / `architecture-design` / `repository-structure` / `glossary-creation` |
| スキル自体の作成・編集 | `writing-skills` |

## コマンド（ユーザー起動のワークフロー入口）

| コマンド | 内容 |
|---|---|
| `/setup-project` | docs/ideas/ の構想メモから文書一式を整備（PRD のみ人間承認） |
| `/add-feature <機能名>` | 設計承認 → 承認後は自律の8ステップ機能追加ループ |
| `/refactor <対象>` | 9原則に基づく6ステップのリファクタリング |
| `/review-docs [パス]` | doc-reviewer サブエージェントによる文書レビュー |

## サブエージェント（.claude/agents/、隔離コンテキストの検証者）

| agent | 役割 |
|---|---|
| `code-reviewer` | 変更差分の2軸レビュー（Standards / Spec）。`requesting-code-review` スキルから起動 |
| `doc-reviewer` | docs/・.steering/ 文書の5軸品質レビュー |
| `implementation-validator` | 実装の静的検証（層規則・設計整合・テスト存在。コード不実行） |

## 鉄則ダイジェスト（詳細は各スキル）

1. 設計承認前に実装しない（`brainstorming`）
2. 失敗するテストなしにプロダクションコードを書かない（`test-driven-development`）
3. 根本原因調査なしに修正しない。3回修正に失敗したら停止して構造を疑う（`systematic-debugging`）
4. 新鮮な検証エビデンスなしに完了を宣言しない（`verification-before-completion`）
5. tasklist.md が作業状態の唯一の真実。全タスク完遂、スキップには理由の明記（`steering`)
