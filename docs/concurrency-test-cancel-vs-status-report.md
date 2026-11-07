# 顧客キャンセル × 店員ステータス更新 同時実行テスト結果

## 概要

同じ注文・同じ明細に対して、次の2つのAPIを実AWS dev環境へほぼ同時に送り、DynamoDBの
条件付き書き込みが設計どおり「どちらか一方だけを成功させる」かを検証した(GitHub Issue #57)。

| 操作 | API | 書き込み方式 |
|---|---|---|
| 顧客のキャンセル | `PATCH /orders/{orderId}/cancel`(order-fn) | `TransactWriteItems`。全明細に`status = WAITING`を条件とする |
| 店員の調理開始 | `PATCH /orders/{orderId}/lines/{lineId}/status`(store-fn) | 単発`UpdateItem`。`status = :from`(WAITING)を条件とする |

- 実行日: 2026-11-07
- 使用スクリプト: `services/scripts/concurrency_test_cancel_vs_status.py`
- 実行コマンド: `python scripts/concurrency_test_cancel_vs_status.py --stage dev --trials 50 --output-json result-50.json`
- パラメータ: `trials=50` `warmup=2`(集計外) `max-offset-ms=30`(2リクエストの送信タイミングを±30msの範囲でランダムにずらす) `store-id=concurrency-test`

### 判定方法

「データが壊れた」と「データは正しいがAPIの返事が不正確」を区別するため、2段階で判定した。

1. **最終状態**(DynamoDBを強整合読み)だけで、どちらの書き込みが反映されたかを決める
   - `cancelled`: 全明細CANCELLED かつ METAもCANCELLED
   - `prepared`: 対象明細PREPARING かつ CANCELLEDがどこにも無い
   - それ以外(一部だけキャンセル、METAと明細の食い違い等)は`inconsistent`(データ不整合)
2. その勝者に対して**応答コード**が正しいかを確かめる
   - `cancelled`ならキャンセル`200`+更新`409`、`prepared`なら更新`200`+キャンセル`409`が正解

## 結果サマリ

**データ不整合は50回中0件。** 両方が成功する・一部だけキャンセルされる、といった不整合は
一度も起きなかった。一方で、**2回(4%)は店員側が`409`ではなく`500`を返した**。

| 最終状態 | キャンセル応答 | 更新応答 | 件数 | 判定 |
|---|---|---|---|---|
| `prepared`(調理開始が勝ち) | `409` | `200` | 30 | ok |
| `cancelled`(キャンセルが勝ち) | `200` | `409` | 18 | ok |
| `cancelled`(キャンセルが勝ち) | `200` | **`500`** | 2 | api_mismatch |

両方の順序(キャンセルが勝つ/調理開始が勝つ)がどちらも十分な回数起きており、片方の順序しか
試せていない、という偏りは無い。送信タイミングのずらし幅ごとの内訳は次のとおり
(負=キャンセル側を遅らせた、正=更新側を遅らせた)。ずらし幅と勝敗がきれいに対応しない
ことから、APIの入口に着いた順番ではなく、Lambda内の処理時間を含めて「DynamoDBへ先に
書き込んだ方」が勝っていることが分かる。

| ずらし幅(ms) | prepared | cancelled |
|---|---|---|
| -30〜-20 | 8 | 0 |
| -20〜-10 | 3 | 5 |
| -10〜0 | 5 | 1 |
| 0〜10 | 5 | 6 |
| 10〜20 | 5 | 4 |
| 20〜30 | 4 | 4 |

## 500の原因

store-fnのCloudWatch Logsに、500を返した2回(trial 13: 20:20:24、trial 19: 20:20:27、いずれもJST)と
同時刻で次の未処理例外が記録されていた。

```
TransactionConflictException: An error occurred (TransactionConflictException)
when calling the UpdateItem operation: Transaction is ongoing for the item
```

DynamoDBでは、`TransactWriteItems`(キャンセル)が処理中の項目に対して単発の`UpdateItem`
(調理開始)が届くと、条件式を評価する前に`TransactionConflictException`で拒否される。
`OrderRepository.update_line_status()`は`ConditionalCheckFailedException`だけを
`LineTransitionConflictError`(→409)に変換しており、この例外は想定外としてそのまま送出され、
store-fnの共通エラーハンドラが500を返していた。

- **データへの影響は無い**: 拒否された側は何も書き込んでおらず、最終状態はキャンセル済みで一貫している
- **店員UIへの影響**: 店員は「調理開始」が409(=他の操作が先に反映された)ではなく、原因不明の
  サーバーエラーとして見える。実際にはキャンセルが成立しているので、正しい応答は409
- 発生条件: 2つの書き込みがDynamoDB上でほぼ完全に重なったときだけ(今回は±30msのずらしで4%)。
  実運用では、お客さんのキャンセルと店員の操作が数十ms以内で重なる頻度はこれよりずっと低い

## 既知の制約

- **キャンセル側の409の内訳は区別できていない**: 逆向きの競合(単発`UpdateItem`の処理中に
  トランザクションが届く)では、キャンセルは`TransactionCanceledException`(理由:
  `TransactionConflict`)で失敗する。`cancel_order()`はこれを条件不成立と同じ
  `OrderNotCancellableError`(409)にまとめているため、応答からは区別できない。結果として
  返る409自体は「調理開始が先に反映された」という実態と一致しており、誤りではない
- 1明細の注文のみを対象にした。複数明細の注文で一部の明細だけ更新と重なる場合も、
  キャンセルは全明細をまとめて条件判定するため同じ結果になる想定だが、今回は実測していない
- 50回のみの試行で、発生率(4%)の精度は高くない

## 再現方法

`services`ディレクトリで、`pip install -e ".[dev,load-test]"`済みの仮想環境に入ってから実行する。
店員アカウントはdev環境のCognitoユーザープールのもの。

```
export STAFF_USERNAME=<店員ユーザー名>
read -s "STAFF_PASSWORD?パスワード: "
export STAFF_PASSWORD
python scripts/concurrency_test_cancel_vs_status.py --stage dev --trials 3
python scripts/concurrency_test_cancel_vs_status.py --stage dev --trials 50 --output-json result-50.json
```

テスト注文は専用の店舗ID`concurrency-test`で作られる。`prepared`になった注文の明細は
その店舗のゾーンキューにPREPARINGのまま残るが、`store-01`など他の店舗には影響しない。
