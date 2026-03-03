---
description: |
  news_trackerリポジトリの24時間以内の活動（Issue, PR, Discussions）を要約し、
  最新のニュース収集状況を日次レポートとして報告します。
on:
  schedule:
    - cron: '0 0 * * *' # 毎日日本時間午前9時（UTC 0:00）に実行
  workflow_dispatch:    # 手動実行も可能

permissions:
  contents: read
  issues: write
  pull-requests: read
  discussions: read

# セーフガード設定: 書き込み操作をIssue作成に制限
safe-outputs:
  create-issue:
    title-prefix: "[Daily Report] "
    labels: [report, automated]

tools:
  github: # GitHub標準ツールを使用
---

# 日次ステータスレポート生成タスク

あなたは `news_tracker` リポジトリの専任エージェントです。
リポジトリの活動を調査し、チームが今日取り組むべき優先事項をまとめてください。

## 調査プロセス
1. **活動の収集**: 過去24時間以内に作成・更新されたIssue、Pull Request、Discussionsをすべて取得してください。
2. **内容の分析**:
   - どこのニュースソース（RSS, API等）でエラーが出ているか？
   - 新しく追加されたトラッキング対象は何か？
   - 議論が止まっている重要なトピックはないか？
3. **レポートの作成**: 以下の構成でMarkdown形式のレポートを作成し、新しいIssueとして投稿してください。

## レポート構成案
- **🚀 今日のサマリー**: 3行でリポジトリの現状を要約。
- **🔍 注目すべき更新**: 重要なPRやマージされた機能。
- **⚠️ 発生中の課題**: エラー報告Issueや未解決のバグ。
- **📝 次のステップ**: 管理者が今日チェックすべき項目。

## スタイルガイド
- プロフェッショナルかつ簡潔なトーンで。
- 重要な項目には絵文字（例: ✅, 🚨）を使い、視覚的にわかりやすくしてください。