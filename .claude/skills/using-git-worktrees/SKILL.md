---
name: using-git-worktrees
description: 現在のワークスペースから隔離した環境で機能開発を始めるときや、実装計画の実行前に使用。ネイティブツールまたは git worktree で隔離ワークスペースを確保する
---

# git worktree の使い方

## 概要

作業を隔離されたワークスペースで行う。プラットフォームのネイティブ worktree ツールを優先し、ネイティブがないときだけ手動の git worktree にフォールバックする。

**基本原則:** 検出 → ネイティブ → git の順。**ハーネスと戦わない。**

**開始時に宣言:** 「using-git-worktrees スキルで隔離ワークスペースを準備する。」

## Step 0: 既存の隔離を検出

**何かを作る前に、既に隔離ワークスペース内にいないか確認する。**

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
BRANCH=$(git branch --show-current)
```

**サブモジュール判定:** `GIT_DIR != GIT_COMMON` はサブモジュール内でも真になる。「既に worktree 内」と結論する前に確認する:

```bash
# パスが返れば worktree ではなくサブモジュール — 通常リポジトリとして扱う
git rev-parse --show-superproject-working-tree 2>/dev/null
```

**`GIT_DIR != GIT_COMMON`（かつ非サブモジュール）:** 既にリンクされた worktree 内。Step 2（セットアップ）へ飛ぶ。**worktree を重ねて作らない。** ブランチ状態を添えて報告する:
- ブランチ上: 「既に隔離ワークスペース `<path>`（ブランチ `<name>`）内にいる」
- detached HEAD: 「既に隔離ワークスペース `<path>` 内（detached HEAD・外部管理）。完了時にブランチ作成が必要」

**`GIT_DIR == GIT_COMMON`（またはサブモジュール）:** 通常のチェックアウト。指示に worktree の希望が示されていればそれに従う。なければ作成前に同意を求める: 「隔離 worktree を用意するか? 現在のブランチを変更から守れる」。拒否されたらその場で作業し Step 2 へ。

## Step 1: 隔離ワークスペースの作成

**必ずこの順で試す。**

### 1a. ネイティブ worktree ツール（最優先）

この環境には **EnterWorktree / ExitWorktree** がある。あるなら**必ず**それを使い、Step 2 へ飛ぶ。

ネイティブツールはディレクトリ配置・ブランチ作成・掃除を自動処理する。ネイティブがあるのに `git worktree add` を使うと、ハーネスから見えない・管理できないファントム状態が生まれる。

`git worktree add` に進むのは**ネイティブツールが存在しない場合のみ**。

### 1b. git worktree フォールバック（ネイティブ不在時のみ）

#### ディレクトリの優先順位（明示指定が常に観測結果に勝つ）

1. **指示に worktree ディレクトリの明示指定があれば**それを使う（質問しない）
2. **既存のプロジェクトローカルディレクトリを確認:**
   ```bash
   ls -d .worktrees 2>/dev/null   # 優先（隠し）
   ls -d worktrees 2>/dev/null    # 代替
   ```
   両方あれば `.worktrees` が勝つ
3. **何の指針もなければ** 既定はプロジェクトルートの `.worktrees/`

#### gitignore 確認（プロジェクトローカルのみ・必須）

```bash
git check-ignore -q .worktrees 2>/dev/null || git check-ignore -q worktrees 2>/dev/null
```

**ignore されていなければ:** `.gitignore` に追記してコミット（例: `chore(git): .worktrees を gitignore に追加`）、その後に作成へ進む。worktree の中身を誤ってコミットするのを防ぐため必須。

#### worktree の作成

```bash
path="$LOCATION/$BRANCH_NAME"
git worktree add "$path" -b "$BRANCH_NAME"
cd "$path"
```

**サンドボックスフォールバック:** 権限エラーで失敗したら、サンドボックスに阻まれた旨を伝え、現在のディレクトリで作業する。セットアップとベースラインテストはその場で実行する。

## Step 2: プロジェクトセットアップ

本プロジェクトは Python 3.12。worktree は独立したチェックアウトなので依存を入れ直す:

```bash
pip install -e ".[dev]" 2>/dev/null || pip install -e .
# requirements.txt があれば: pip install -r requirements.txt
```

## Step 3: クリーンなテストベースラインの確認

```bash
python -m pytest tests/ -q --tb=line
```

**失敗した場合:** 失敗ベースラインを報告し、続行するか調査するかを確認する。既存の失敗と新規バグを区別できなくなるため、黙って進めない。

**成功した場合:** 準備完了を報告する:

```
worktree 準備完了: <フルパス>
テスト成功 (<N>件, 失敗0)
<機能名> の実装を開始できる
```

## クイックリファレンス

| 状況 | 行動 |
|------|------|
| 既にリンクされた worktree 内 | 作成しない (Step 0) |
| サブモジュール内 | 通常リポジトリとして扱う |
| ネイティブツールあり (EnterWorktree) | 必ずそれを使う (Step 1a) |
| ネイティブなし | git worktree (Step 1b) |
| `.worktrees/` と `worktrees/` 両方あり | `.worktrees/` を使う |
| ディレクトリ未 ignore | .gitignore 追記 + コミット |
| 作成が権限エラー | その場で作業（フォールバック） |
| ベースラインでテスト失敗 | 報告して確認を取る |

## Red Flags

**決してしないこと:**
- Step 0 で既存の隔離を検出したのに worktree を作る
- ネイティブツール（EnterWorktree）があるのに `git worktree add` を使う — **これが最多の失敗**
- Step 1a を飛ばして Step 1b の git コマンドに直行する
- ignore 未確認でプロジェクトローカル worktree を作る
- ベースラインテスト確認を省く / 失敗したまま無断で進む

**必ずすること:** Step 0 の検出を最初に実行 / ネイティブ優先 / 優先順位（明示指定 > 既存ディレクトリ > 既定）に従う / ignore 確認 / セットアップ実行 / クリーンベースライン確認。
