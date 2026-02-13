# 🚀 Daily Dev Digest

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

## Notion データベース設計

### 1つのデータベースで全アイテムを管理

| プロパティ | 型 | 値 | 説明 |
|---|---|---|---|
| **Title** | Title | `2026-02-13 Daily Digest` / `React Server Componentsを学ぶ` | アイテム名 |
| **Type** | Multi-select | `digest` / `learning` / `news` / `action` / `idea` / `request` | 行の種類 |
| **Status** | Status | `Not Started` / `In Progress` / `Done` | ユーザーが進捗管理 |
| **Date** | Date | `2026-02-13` | 生成日 or リクエスト日 |
| **Priority** | Multi-select | `High` / `Medium` / `Low` | アクション等の優先度 |
| **Rating** | Multi-select | `★1` / `★2` / `★3` / `★4` / `★5` | ユーザーによる生成物の評価 |
| **Source** | Multi-select | `claude` / `user` | 誰が作ったか |
| **Parent Digest** | Relation (self) | → `2026-02-13 Daily Digest` | 個別アイテムを日次サマリーに紐づけ |
| **Tags** | Multi-select | `react`, `python`, `infra` 等 | 技術タグ |

### Type の説明

| Type | Source | 内容 |
|---|---|---|
| `digest` | claude | 日次サマリー（1日1件）。本文に開発状況まとめを記載 |
| `learning` | claude | 学習トピック × 3。プロジェクトに関連する学習テーマ |
| `news` | claude | 関連ニュース × 3。web searchで取得した技術トレンド |
| `action` | claude | 今日のアクション × 3-5。優先度付きToDo |
| `idea` | claude | プロジェクトアイデア × 1-2 |
| `request` | user | ユーザーからClaudeへの調査依頼。次回実行時に回答 |

### データフロー

```
── 毎朝の実行 ──────────────────────────────────
  1. Status が Not Started の request を取得（ユーザーからの依頼）
  2. 過去アイテムの Rating を取得し傾向を分析
     - ★4-5 が多いタグ・テーマ → 類似の提案を増やす
     - ★1-2 → 類似の提案を避ける
  3. GitHub活動を取得
  4. Claude分析（リクエスト回答 + フィードバック反映）
  5. digest ページを1件作成
  6. 個別アイテム（learning/news/action/idea）を各1行ずつ作成
     → Parent Digest でサマリーにリレーション
  7. 回答済み request の Status を Done に更新

── ユーザー側 ──────────────────────────────────
  - action/learning の Status を In Progress / Done で管理
  - Rating で生成物を評価 → 次回以降の提案精度が向上
  - 新しい request 行を手動追加 → 次回実行時にClaudeが拾って回答
```

---

## セットアップ

### 1. Notion の準備

#### データベース作成
1. Notion で新しいデータベースを作成
2. 以下のプロパティを追加:
   - `Type`（マルチセレクト）: `digest`, `learning`, `news`, `action`, `idea`, `request`
   - `Status`（ステータス）: `Not Started`, `In Progress`, `Done`
   - `Date`（日付）
   - `Priority`（マルチセレクト）: `High`, `Medium`, `Low`
   - `Rating`（マルチセレクト）: `★1`, `★2`, `★3`, `★4`, `★5`
   - `Source`（マルチセレクト）: `claude`, `user`
   - `Parent Digest`（リレーション）: 同じデータベースへのセルフリレーション
   - `Tags`（マルチセレクト）

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

### 2. APIキーの準備

| キー | 取得場所 |
|---|---|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com/settings/keys |
| `NOTION_TOKEN` | 上記のNotion Integration設定 |
| `NOTION_DATABASE_ID` | 上記のURL |
| `GITHUB_TOKEN` (任意) | https://github.com/settings/tokens → `repo`スコープ |

### 3. GitHub Actions で動かす

1. このリポジトリをGitHubにpush
2. Settings → Secrets and variables → Actions で以下を設定:
   - **Secrets**: `ANTHROPIC_API_KEY`, `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `GH_PAT`(任意)
   - **Variables**: `TARGET_GITHUB_USERNAME`（デフォルト: HayatoShimada）
3. Actions タブ → 「Daily Dev Digest」→ 「Run workflow」で手動テスト

### 4. ローカルで動かす（テスト用）

```bash
# 依存インストール
pip install -r requirements.txt

# 環境変数を設定
cp .env.example .env
# .env を編集

# 実行（python-dotenv未使用のため、直接exportするか以下のように）
export $(cat .env | xargs) && python daily_digest.py
```

---

## カスタマイズ

### 実行時間の変更
`.github/workflows/daily-digest.yml` の cron を変更:
```yaml
# 例: 毎朝9時(JST) = UTC 0:00
- cron: '0 0 * * *'
```

### Notionデータベースのビュー活用例
- **Board ビュー**: Status でグループ化 → カンバン風にタスク管理
- **Table ビュー**: Type でフィルタ → `request` だけ表示して依頼管理
- **Calendar ビュー**: Date で表示 → 日次ダイジェストを時系列で確認
- **Gallery ビュー**: Rating でソート → 高評価アイテムを振り返り

### AIのプロンプト調整
`generate_suggestions()` 内の `system_prompt` を編集して、自分の状況に合わせた提案を得られます。

---

## コスト目安

- **Claude API**: 1回あたり約 $0.01〜0.05（Sonnet + web search）
- **GitHub API**: 無料（認証なし60回/h、認証あり5000回/h）
- **Notion API**: 無料
- **GitHub Actions**: 無料（パブリックリポ）/ 2000分/月（プライベート Free プラン）

月額約 **$1〜2** 程度です。

---

## ライセンス

MIT