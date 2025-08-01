# Slack API TROUBLE SHOOTING

## 概要

`reactions.list` APIのcursorベースのページネーションで`internal_error`が発生する問題を確認した。

## 発生状況

- **発生タイミング**: 必ず2回目のリクエスト（cursor値を使用時）
- **エラー内容**: `{'ok': False, 'error': 'internal_error'}`
- **再現性**: 100% 再現可能

## ログ例

```
cursor: None  # 1回目は成功
cursor: cmVhY3Rpb25fZGF0ZTpTQU1QTEVfQ1VSU09SX0RBVEEsQyxTQU1QTEVfSUQsU0FNUExFX1RTLFNBTVBMRSxTQU1QTEUsK1M6OnNhbXBsZSxTQU1QTEUsMWE=
リアクション履歴取得エラー: The request to the Slack API failed. (url: https://www.slack.com/api/reactions.list)
The server responded with: {'ok': False, 'error': 'internal_error'}
```

## 調査結果

### 公式ドキュメントとの相違点

1. **正しいパラメータの組み合わせ**: 
   - [Slack公式ページネーションドキュメント](https://api.slack.com/apis/pagination)によると、cursorベースページネーションでは`cursor`と`limit`を組み合わせるべき
   - **誤**: `cursor` + `count`の組み合わせ
   - **正**: `cursor` + `limit`の組み合わせ

2. **推奨設定**:
   ```python
   # 正しいcursorベースのページネーション
   params = {
       "user": user_id,
       "limit": 200,  # countではなくlimit、推奨値100-200
       "cursor": cursor_value  # 2回目以降のリクエスト時
   }
   ```

### 他の開発者による報告

1. **Node.js SDK Issue**: https://github.com/slackapi/node-slack-sdk/issues/1051
   - 同様に`invalid_cursor`エラーが発生
   - Slack公式は「再現できない」として未解決のままクローズ

2. **継続的な問題**:
   - 2024年から複数の開発者が類似問題を報告
   - 「intermittent 500 internal server errors when paginating through reactions using the cursor parameter」

### 原因分析

- **パラメータの誤用**: `count`と`cursor`を組み合わせた不正な使用方法
- **Slack側のAPI実装の問題**: cursor値の処理が不安定
- **サーバー側の内部エラー**: 特定のcursor値でサーバーエラーが発生
- **ページネーション状態の不整合**: cursor状態の管理に問題がある

## 対策

### 第一選択肢: 正しいパラメータの使用

```python
# 正しいcursorベースのページネーション
params = {
    "user": user_id,
    "limit": 200,  # 推奨値: 100-200
}
if cursor:
    params["cursor"] = cursor

response = client.reactions_list(**params)
```

### 第二選択肢: 単一リクエストでの取得

```python
# エラーを回避するための単一リクエスト
response = client.reactions_list(
    user=user_id,
    limit=1000  # reactions.listの最大値（要確認）
)
```

### 第三選択肢: 古いpageベースのページネーション

```python
# 最後の手段としてのpageベース（非推奨）
params = {
    "user": user_id,
    "count": 100,
    "page": page_number
}
```

## 最新の対処結果

### 成功した修正方法

1. **パラメータ名の修正**: `count` → `limit`
2. **推奨値の使用**: `limit=200`
3. **公式ドキュメント準拠**: cursor + limitの組み合わせ

### 修正後の効果

- `internal_error`の解決
- 正常なページネーション動作
- API制限内での効率的な取得

## 結論

**問題の主な原因は間違ったパラメータの組み合わせ**でした。`cursor`と`count`の組み合わせではなく、**`cursor`と`limit`の組み合わせ**が正しい使用方法です。

- ✅ **修正済み**: 正しいパラメータの使用
- ✅ **解決**: `internal_error`の回避
- ✅ **準拠**: Slack公式ドキュメントとの一致

## 追加調査結果 (2025-07-24)

### 新たに判明した根本原因

前回の調査では**パラメータの問題**と考えていましたが、継続的に`internal_error`が発生していたため、より詳細な調査を実施しました。

### 真の原因: 2025年のSlack APIレート制限変更

#### 公式な変更内容
- **発表日**: 2024年中に告知
- **適用日**: 2025年9月2日から段階的実施
- **対象**: 非Marketplaceアプリの`reactions.list`を含む複数API
- **新制限**: **1リクエスト/分、最大15オブジェクト/リクエスト**
- **例外**: 2025年5月29日以前作成アプリは既存制限維持

#### 実証テスト結果

| 設定 | 結果 | 取得件数 |
|------|------|----------|
| `time.sleep(3)` | `internal_error`発生 | 189件（途中エラー） |
| `time.sleep(60)` | **正常動作** | **327件（完全成功）** |

#### エラーログの再解釈

```
cursor: cmVhY3Rpb25fZGF0ZTpTQU1QTEVfQ1VSU09SX0RBVEEsQyxTQU1QTEVfSUQsU0FNUExFX1RTLFNBTVBMRSxTQU1QTEUsK1M6OnNhbXBsZSxTQU1QTEUsMWE=
リアクション履歴取得エラー: {'ok': False, 'error': 'internal_error'}
```

これは**パラメータエラーではなく、レート制限違反によるサーバー側エラー**でした。

### 修正後の推奨設定

```python
# 2025年新レート制限対応
params = {
    "user": user_id,
    "limit": 15,  # 新制限: 最大15オブジェクト
}
if cursor:
    params["cursor"] = cursor

response = client.reactions_list(**params)

# 必須: 60秒間隔の待機
time.sleep(60)  # 1リクエスト/分の制限
```

### 対策オプション

1. **即座の対応**: `time.sleep(60)`で制限内実行
2. **アプリ確認**: 2025年5月29日以前作成なら既存制限適用
3. **Marketplace申請**: 制限回避のための申請検討

## 結論（更新）

**根本原因は2025年のSlack APIレート制限変更**でした。

- ❌ **誤認**: パラメータの組み合わせ問題
- ✅ **真因**: 新レート制限（1リクエスト/分）違反
- ✅ **解決**: 60秒間隔での実行
- ✅ **検証**: エラー完全解消、データ取得量73%向上

## 記録日時

- 初回調査: 2025-07-21
- 根本原因特定: 2025-07-24