# AWS_OrderSystem — Project Rules

## Git ブランチ命名

| プレフィックス | 用途 |
|---|---|
| `feat/` | 新機能 |
| `fix/` | バグ修正 |
| `refactor/` | リファクタリング |
| `chore/` | 保守・依存関係更新 |
| `docs/` | ドキュメントのみ |

例: `feat/websocket-connect-fn` / `fix/order-idempotency-key`

## コミットメッセージ（Conventional Commits）

フォーマット: `type(scope): 説明`

**スコープ一覧**:

| スコープ | 対象 |
|---|---|
| `menu` | menu-fn / メニューUI |
| `cart` | cart-fn / カートUI |
| `order` | order-fn / 注文フロー |
| `status` | status-fn / ステータス表示 |
| `store` | store-fn / スタッフUI |
| `ws` | WebSocket（connect/disconnect/push-fn） |
| `router` | machine-router-fn / SQS振り分け |
| `cdk` | インフラ（CDK） |
| `ci` | GitHub Actions |
| `deps` | 依存関係更新 |

例:
```
feat(ws): add connect-fn storing connectionId to ConnectionTable
fix(store): prevent status revert after undo banner timeout
chore(cdk): upgrade CDK to v2.180.0
```

## マージ戦略

- `main` への直接 push は禁止。必ず PR を経由する
- マージ方式は **Squash merge**（main のコミット履歴を綺麗に保つ）
- CI（lint / test / security / cdk-synth / build）が全て通過してからマージする

## モデル運用

- 通常の実装作業（コーディング・テスト・細かい修正）はデフォルトのSonnetセッションで行う
- AWSアーキテクチャ・インフラ構成・使用サービス/フレームワークの比較検討は `architect` サブエージェントに委譲する
- 特に難易度が高く後戻りしにくい設計判断（マルチエージェント構成の根幹、データモデルの全体設計など）は `frontier-design` サブエージェントに委譲する
- 上記に該当するタスクが来たら、ユーザーに確認せず自動的に適切なサブエージェントを使う
- advisor（Fable、自動発火）は会話の流れを保ったまま軽く一声かける用途、`frontier-design` は独立コンテキストで重い意思決定を深く検討させる用途、と役割が異なる。両方を機械的に併用しない
