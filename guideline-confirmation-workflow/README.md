# ガイドライン確認ワークフロー

ガイドラインの既読確認とランダムクイズで理解度を記録する Slack ワークフロー。

## セットアップ

```bash
# ローカル開発
slack run

# 本番デプロイ
slack install --environment deployed  # 管理者承認が必要
slack deploy
slack trigger create --trigger-def triggers/link_trigger.ts

# 環境変数
slack env add NOTIFY_USER_ID <通知先ユーザーID>
slack env add ADMIN_CHANNEL <管理者チャンネルID>   # 任意
slack env add TOOL_NAME <ツール名>                  # トリガー表示名に使用
```

## フロー

```
リンクトリガー
  → ガイドライン確認モーダル（「理解しました」）
    → 理解度テスト 1/N → 解説表示 → 2/N → ... → N/N
      → 全問正解 → クリア記録 → 完了
      → 不正解あり → 追試（不正解の問題を再出題、全問正解まで繰り返し）
```

## Datastore

| テーブル | 記録タイミング | 確認コマンド |
|---|---|---|
| `confirmation_results` | 「理解しました」押下時 | `slack datastore query '{"datastore": "confirmation_results"}'` |
| `quiz_results` | 各問題の回答時 | `slack datastore query '{"datastore": "quiz_results"}'` |
| `quiz_cleared` | 全問正解時 | `slack datastore query '{"datastore": "quiz_cleared"}'` |

## ファイル構成

| レイヤー | ファイル | 役割 |
|---|---|---|
| エントリポイント | `manifest.ts` | アプリ定義（名前・ワークフロー・Datastore・スコープの登録） |
| トリガー | `triggers/link_trigger.ts` | リンクトリガー定義（共有URLからワークフローを起動） |
| ワークフロー | `workflows/guideline_confirmation_workflow.ts` | ワークフロー定義（interactivity・user_idを受け取りFunctionを呼び出す） |
| Function | `functions/guideline_confirmation.ts` | メインオーケストレーター（モーダル開始→確認→クイズ出題→正誤判定→追試→完了のハンドラチェーン） |
| View | `functions/views/guideline_view.ts` | ガイドライン確認モーダルのBlock Kit構築 |
| View | `functions/views/quiz_view.ts` | クイズ出題モーダルのBlock Kit構築（前問解説・進捗表示含む） |
| View | `functions/views/result_view.ts` | 全問正解結果モーダルのBlock Kit構築 |
| Operation | `functions/operations/record_and_notify.ts` | 業務ロジック（ユーザー名解決・確認記録・クイズ結果記録・クリア記録・管理者/DM通知） |
| Data | `data/quiz_loader.ts` | クイズJSON読み込み・ランダム取得・ID検索 |
| Data | `data/quizzes.json` | クイズ設問データ（11問） |
| Data | `data/guideline.json` | ガイドラインのタイトル・URL・要約 |
| Datastore | `datastores/confirmation_results.ts` | 「理解しました」確認記録テーブル定義 |
| Datastore | `datastores/quiz_results.ts` | 理解度テスト回答記録テーブル定義 |
| Datastore | `datastores/quiz_cleared.ts` | 理解度テスト全問正解（クリア）記録テーブル定義 |
| Storage | `storage/interface.ts` | ストレージ抽象インターフェース（3レコード型 + StorageProvider） |
| Storage | `storage/slack_datastore.ts` | Slack Datastore実装 |
| Storage | `storage/spreadsheet.ts` | Google Spreadsheet Webhook実装 |
| Storage | `storage/factory.ts` | 環境変数でストレージ実装を切り替えるファクトリ |
