# AWS_OrderSystem（モバイルオーダーアプリ）

![Next.js](https://img.shields.io/badge/next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/-ReactJs-61DAFB?logo=react&logoColor=white&style=for-the-badge)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/tailwindcss-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![AWS Lambda](https://img.shields.io/badge/AWS%20Lambda-FF9900?style=for-the-badge&logo=awslambda&logoColor=white)
![Amazon DynamoDB](https://img.shields.io/badge/DynamoDB-4053D6?style=for-the-badge&logo=amazondynamodb&logoColor=white)
![AWS CDK](https://img.shields.io/badge/AWS%20CDK-527FFF?style=for-the-badge&logo=amazonaws&logoColor=white)
![pytest](https://img.shields.io/badge/pytest-0A9EDC?style=for-the-badge&logo=pytest&logoColor=white)
![Jest](https://img.shields.io/badge/Jest-C21325?style=for-the-badge&logo=jest&logoColor=white)

## プロジェクト概要

カフェ向けモバイルオーダーアプリ。お客様はQRコードからWebページを開いて商品を注文し、店舗に着いたタイミングで受け取れる体験を提供する（決済はレジでの会計のみ、アプリ内決済は対象外）。フロントエンド（Next.js）・バックエンド（Python Lambda）・インフラ（AWS CDK）を1リポジトリで管理するモノレポ構成。

詳細なAPI契約・DynamoDBキー設計は [`docs/architecture.md`](docs/architecture.md)、要件定義は [`docs/requirements.md`](docs/requirements.md)（非エンジニア向けは [`docs/requirements-plain.md`](docs/requirements-plain.md)）を参照。

## 必要な環境変数・コマンドの一覧

### 環境変数

| 変数名 | 対象 | 説明 |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `web/` | API Gateway のベースURL。未設定時はdev環境のURLにフォールバックする（[`web/src/lib/api.ts`](web/src/lib/api.ts)） |
| `TABLE_NAME` | `services/`（Lambda実行時） | DynamoDBテーブル名。CDKがLambdaに自動設定するため、ローカルでの手動設定は不要（[`services/src/config.py`](services/src/config.py)） |
| `STAGE` / `--context stage=` | `infra/` | デプロイ先ステージ（`dev` \| `prod`）。CDKコマンド実行時に指定する（[`infra/bin/app.ts`](infra/bin/app.ts)） |

<!-- TODO: AWS認証情報（プロファイル名等）やCDKブートストラップ済みアカウントの情報を追記 -->

### 主要コマンド

| ディレクトリ | コマンド | 内容 |
|---|---|---|
| `web/` | `npm run dev` | 開発サーバー起動（`http://localhost:3000`） |
| `web/` | `npm run build` | 静的エクスポートビルド（`out/`を生成） |
| `web/` | `npm run lint` | ESLint |
| `services/` | `pytest` | ユニットテスト |
| `services/` | `ruff check .` | Lint |
| `services/` | `mypy src` | 型チェック |
| `infra/` | `npm run build` | TypeScriptの型チェック |
| `infra/` | `npm run test` | Jestテスト（cdk-nagのセキュリティチェックを含む） |
| `infra/` | `npx cdk synth --context stage=dev` | CloudFormationテンプレートの合成 |
| `infra/` | `npx cdk deploy --all --context stage=dev` | dev環境へデプロイ |

## ディレクトリ構成

```
.
├── web/        # フロントエンド（Next.js App Router、静的エクスポート）
│   └── src/
│       ├── app/         # ルート単位のページ（Server Componentの薄いShell）
│       ├── components/  # "use client" のUI本体
│       └── lib/         # APIクライアント・sessionId管理などのロジック
├── services/   # バックエンド（Python Lambda）
│   ├── src/
│   │   ├── handlers/    # HTTP Lambdaのハンドラ（外殻、薄く保つ）
│   │   ├── domain/      # ドメインモデル・ビジネスロジック
│   │   └── adapters/    # DynamoDB等の外部リソースアクセス
│   ├── tests/           # pytest
│   └── scripts/         # シード投入等の運用スクリプト
├── infra/      # インフラ（AWS CDK, TypeScript）
│   ├── bin/app.ts        # CDK Appエントリーポイント
│   ├── lib/              # スタック定義（Stateful/App）
│   └── test/             # Jest + cdk-nag
├── docs/       # 設計書・要件定義書
└── tasks/      # 実装計画・進捗記録（Gitでは追跡対象外）
```

## 開発環境の構築手順

### 前提条件

- Node.js（`web/`・`infra/`共にnpmで依存解決。バージョン指定は現状なし）
- Python 3.12以上
- AWS CLI設定済み・CDKブートストラップ済みのAWSアカウント（`infra/`のデプロイに必要）

### セットアップ

1. リポジトリをクローン
   ```bash
   git clone git@github.com:Masaharu1223/AWS_OrderSystem.git
   cd AWS_OrderSystem
   ```

2. フロントエンド（`web/`）
   ```bash
   cd web
   npm install
   npm run dev
   ```
   `http://localhost:3000` を開く。

3. バックエンド（`services/`）
   ```bash
   cd services
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   pytest
   ```

4. インフラ（`infra/`）
   ```bash
   cd infra
   npm install
   npm run build
   npx cdk synth --context stage=dev
   ```
   実際にAWSへデプロイする場合は `npx cdk deploy --all --context stage=dev` を実行する（既存のAWSリソースに影響するため、実行前に対象アカウント・リージョンを確認すること）。

## トラブルシューティング

- **`npm run build`（`web/`）が失敗する / 型が合わない**: このリポジトリのNext.jsは訓練データと異なるバージョンの可能性がある。`web/AGENTS.md`が示す通り、`web/node_modules/next/dist/docs/`配下の同梱ドキュメントを確認すること。
- **フロントエンドから`GET /menu`等がブラウザでブロックされる（CORSエラー）**: `infra/lib/app-stack.ts`のCORS設定（`allowOrigins`）に、アクセス元のオリジンが含まれているか確認する。CDK側の設定変更は`cdk deploy`を実行するまで実際のAPI Gatewayには反映されない。
- **Lambda起動時に`TABLE_NAME environment variable is required`エラー**: ローカルでLambdaハンドラを直接実行しようとした場合に発生する。`TABLE_NAME`はCDKがデプロイ時にLambdaへ自動設定する値のため、ローカル実行時は環境変数を手動で設定するか、pytest（`moto`でDynamoDBをモック）経由でテストすること。

<!-- TODO: 実際に開発を進める中で遭遇したハマりどころがあれば追記 -->
