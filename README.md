# Daily Dev Digest

GitHub の開発活動を毎日分析し、**学習すべきこと・関連ニュース・次のアクション・プロジェクトアイデア**を Notion に自動投稿するツールです。

## 仕組み

```
GitHub API  →  開発状況を収集
     ↓
Notion API  →  過去のRating・未処理Requestを取得
     ↓
Claude API  →  AI分析（web search + フィードバック反映 + リクエスト回答）
     ↓
Notion API  →  データベースにアイテム作成・Request更新
     ↓
GitHub Actions  →  毎朝8時(JST)に自動実行
```

---

## セットアップ

### 1. GitHub Token の取得

このツールは GitHub API でユーザーの公開アクティビティを取得します。トークンなしでも動作しますが、レートリミットが 60回/時 に制限されます。トークンを設定すると 5,000回/時 になります。

#### Fine-grained Personal Access Token（推奨）

1. https://github.com/settings/personal-access-tokens/new にアクセス
2. 以下を入力:
   - **Token name**: `Daily Dev Digest`
   - **Expiration**: 任意（90日 or カスタム）
   - **Resource owner**: 自分のアカウント
   - **Repository access**: `Public Repositories (read-only)` を選択
   - **Permissions**: デフォルトのまま（追加のスコープ不要）
3. 「Generate token」をクリック
4. 表示されたトークン（`github_pat_...`）をコピーして保存

> **注意**: トークンはこの画面でしか表示されません。閉じる前に必ずコピーしてください。

#### Classic Personal Access Token

Fine-grained が使えない場合はこちら:

1. https://github.com/settings/tokens/new にアクセス
2. 以下を入力:
   - **Note**: `Daily Dev Digest`
   - **Expiration**: 任意
   - **Scopes**: なし（公開イベントの取得にスコープは不要。レートリミット緩和のみが目的）
3. 「Generate token」をクリック
4. 表示されたトークン（`ghp_...`）をコピーして保存

### 2. Notion の準備

#### データベース作成

1. Notion で新しいデータベースを作成
2. 以下のプロパティを追加:

| プロパティ名 | 型 | 選択肢 |
|---|---|---|
| `Type` | マルチセレクト | `digest`, `learning`, `news`, `action`, `idea`, `request` |
| `Status` | ステータス | `Not Started`, `In Progress`, `Done` |
| `Date` | 日付 | — |
| `Priority` | マルチセレクト | `High`, `Medium`, `Low` |
| `Rating` | マルチセレクト | `★1`, `★2`, `★3`, `★4`, `★5` |
| `Source` | マルチセレクト | `claude`, `user` |
| `Parent Digest` | リレーション | 同じデータベースへのセルフリレーション |
| `Tags` | マルチセレクト | （自動で追加される） |

#### Notion Integration 作成

1. https://www.notion.so/profile/integrations にアクセス
2. 「新しいインテグレーション」をクリック
3. 名前を入力（例: `Daily Dev Digest`）
4. 「送信」→ トークンをコピー → **`NOTION_TOKEN`** として保存

#### データベースにインテグレーションを接続

1. 作成したデータベースページを開く
2. 右上の `•••` → 「コネクトの追加」 → 作成したインテグレーションを選択

#### データベースIDの取得

データベースのURLから取得:
```
https://www.notion.so/xxxxx?v=yyyyy
                       ^^^^^
                  この部分がDATABASE_ID
```

### 3. Claude API キーの取得

1. https://console.anthropic.com/settings/keys にアクセス
2. 「Create Key」をクリック
3. 表示されたキー（`sk-ant-...`）をコピーして保存

### 4. 環境変数の一覧

| キー | 必須 | 説明 |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API キー |
| `NOTION_TOKEN` | Yes | Notion Integration トークン |
| `NOTION_DATABASE_ID` | Yes | Notion データベース ID |
| `GITHUB_TOKEN` | No | GitHub Personal Access Token（レートリミット緩和） |
| `TARGET_GITHUB_USERNAME` | No | 対象の GitHub ユーザー名（デフォルト: `HayatoShimada`） |

---

## 実行方法

### ローカル実行

```bash
pip install -r requirements.txt

cp .env.example .env
# .env を編集してAPIキーを設定

export $(cat .env | xargs) && python daily_digest.py
```

### GitHub Actions（自動実行）

1. リポジトリを GitHub に push
2. **Settings → Secrets and variables → Actions** で設定:

   **Secrets**:
   - `ANTHROPIC_API_KEY`
   - `NOTION_TOKEN`
   - `NOTION_DATABASE_ID`
   - `GH_PAT`（GitHub Token、任意）

   **Variables**:
   - `TARGET_GITHUB_USERNAME`（デフォルト: `HayatoShimada`）

3. **Actions タブ → 「Daily Dev Digest」→ 「Run workflow」** で手動テスト

毎朝 8:00 JST に自動実行されます。

---

## 使い方

### Notion に投稿される内容

毎回の実行で以下が作成されます:

| Type | 件数 | 内容 |
|---|---|---|
| `digest` | 1 | 日次サマリー。本文に開発状況まとめ |
| `learning` | 3 | プロジェクトに関連する学習トピック |
| `news` | 3 | web search で取得した技術ニュース |
| `action` | 3-5 | 優先度付き ToDo リスト |
| `idea` | 1-2 | プロジェクトアイデア |

### 生成物を評価する

各アイテムの `Rating` に ★1〜★5 をつけると、次回以降の提案に反映されます:
- ★4-5 が多いタグ → 類似の提案が増える
- ★1-2 が多いタグ → 類似の提案が減る

### Claude にリクエストを送る

Notion データベースに手動で行を追加:
- **Type**: `request`
- **Source**: `user`
- **Status**: `Not Started`
- **Title**: 調べてほしい内容（例: 「Next.js App Router のベストプラクティス」）

次回実行時に Claude が回答し、Status が `Done` に更新されます。

---

## カスタマイズ

### 実行時間の変更

`.github/workflows/daily-digest.yml` の cron を変更:
```yaml
# 例: 毎朝9時(JST) = UTC 0:00
- cron: '0 0 * * *'
```

### Notion ビューの活用例

- **Board ビュー**: Status でグループ化 → カンバン風にタスク管理
- **Table ビュー**: Type でフィルタ → `request` だけ表示して依頼管理
- **Calendar ビュー**: Date で表示 → 日次ダイジェストを時系列で確認

### AI プロンプトの調整

`daily_digest.py` の `SYSTEM_PROMPT` を編集して、自分の状況に合わせた提案を得られます。

---

## コスト目安

| サービス | コスト |
|---|---|
| Claude API | 1回あたり約 $0.01〜0.05（Sonnet + web search） |
| GitHub API | 無料 |
| Notion API | 無料 |
| GitHub Actions | 無料（パブリック）/ 2000分/月（プライベート Free プラン） |

月額約 **$1〜2** 程度です。

---

## ライセンス

MIT
# news_tracker
