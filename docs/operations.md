# 運用メモ — CDKの外で管理しているもの・手作業の手順

**作成日**: 2026-11-15
**対象読者**: このリポジトリをデプロイ・運用する人

インフラは基本的に CDK（`infra/`）で作っています。ただし、**秘密情報や外部サービスとの連携は CDK の外で手作業で管理**しています。秘密情報をテンプレートや Git に残さないためです。
ここには「CDK を見ても分からないもの」と、その手順をまとめます。

---

## 1. CDKの外で管理しているもの一覧

| もの | 置き場所 | 作り方 | 使っているところ |
|---|---|---|---|
| GitHub トークン（Amplify 連携用） | Secrets Manager `mobile-order/github-amplify-token`（ap-northeast-1、プレーンテキスト） | 手作業（§2） | Amplify アプリの作成・更新時（`infra/lib/constructs/web-hosting.ts` が動的参照で渡す） |
| AWS Amplify の GitHub App | GitHub の「AWS Amplify (ap-northeast-1)」アプリ。**このリポジトリだけ**に許可 | 手作業（初回のみ） | Amplify が GitHub からソースを取得し、`main` への push を検知する |
| 受渡検知の合言葉 | SSM SecureString `/mobile-order/{stage}/handover-api-key` | 手作業 | store-fn の `PATCH .../handover`（architecture.md §7.5） |
| PayPay の API キー・シークレット | SSM SecureString `/mobile-order/{stage}/payment/paypay/api-key`・`.../api-secret` | 手作業（実決済を始めるとき） | order-fn・status-fn（`PAYMENT_PROVIDER=paypay` のときだけ） |
| 店員のログインアカウント | Cognito ユーザープール（`MobileOrder-{stage}-Stateful`） | 手作業（セルフサインアップは無効） | スタッフ画面のログイン |
| CDK コンテキスト | `cdk deploy` の `--context` | デプロイのたびに指定 | `paymentProvider`（既定 `auto-approve`）、`paypayRedirectUrl`（既定は Amplify の `<WebUrl>/order/`） |

CDK は SSM パラメータ・シークレットを**作りません**。名前で参照して、読む権限を付けるだけです。
- GitHub トークンのシークレットが無いと、`cdk deploy` が失敗します（デプロイ時に値を読むため）
- SSM パラメータが無くてもデプロイは通ります。実行時に、それを使う処理（受渡検知・PayPay 決済）だけが失敗します

---

## 2. GitHub トークンの更新

### いつ必要か

- 今のトークンは classic PAT（スコープ `admin:repo_hook` のみ）で、2026-11-10 に有効期限 90 日で作成しました。**2027-02-08 ごろに期限が切れます**。
- Amplify はこのトークンを保存しません（[AWS::Amplify::App のリファレンス](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-amplify-app.html)）。作成後のビルドは GitHub App 経由で動くので、**期限が切れても `main` への push による自動ビルドは止まらない見込み**です。
- ただし、Amplify アプリの作成・更新 API はトークンを受け取ります（[UpdateApp](https://docs.aws.amazon.com/amplify/latest/APIReference/API_UpdateApp.html)）。期限切れのまま CDK で Amplify アプリを作り直す・更新すると失敗する可能性があります。**期限前に更新しておく**のが安全です。

### 手順

1. GitHub の Settings → Developer settings → Personal access tokens (classic) で、新しいトークンを作る
   - スコープは `admin:repo_hook` だけにする
2. AWS コンソールの Secrets Manager で `mobile-order/github-amplify-token` を開き、「シークレットの値を取得する」→「編集する」で新しいトークンに置き換える
   - **トークンをコマンドに直接書かない**でください。シェルの履歴に残ります。コンソールで貼り付けるのが安全です
3. 値が更新されたことを、値を表示せずに確認する
   ```
   aws secretsmanager describe-secret --secret-id mobile-order/github-amplify-token
   ```
   `LastChangedDate` が今日になっていれば OK です
4. GitHub で古いトークンを削除する
5. この文書の「2027-02-08 ごろ」の日付を、新しい期限に書き換える

シークレットの値を変えただけでは、CloudFormation はトークンを Amplify に送り直しません。次に Amplify アプリが更新されるときに、新しい値が使われます。

---

## 3. Amplify（フロントエンド配信）の操作

dev のフロントは `https://main.d2fp0vxtbkuvla.amplifyapp.com`（CDK の出力 `WebUrl`）、Amplify のアプリ ID は `d2fp0vxtbkuvla`（出力 `AmplifyAppId`）です。

### 自動ビルド

`main` にマージすると、Amplify が自動でビルドして公開します。ビルドの内容はリポジトリ直下の `amplify.yml` に書いてあります。

### 手動でビルドしたいとき

次のようなときは、手動でビルドを始めます。
- Amplify アプリを初めて作ったとき（CDK はビルドを始めません）
- API の URL などが変わったとき（下記）

貼り付けで行末が切れないよう、先にリージョンを設定してから実行します。

```
export AWS_REGION=ap-northeast-1
```
```
aws amplify start-job --app-id d2fp0vxtbkuvla --branch-name main --job-type RELEASE
```

### API の URL・店員ログイン ID が変わったとき

`NEXT_PUBLIC_API_BASE_URL`・`NEXT_PUBLIC_STAFF_CLIENT_ID` は、**ビルドのときに JavaScript へ埋め込まれます**。
CDK が新しい値を Amplify の環境変数に入れても、公開中のサイトは古い値のままです。`cdk deploy` のあと、上の手順でビルドし直してください。

### ローカル開発

`web/.env.example` を `web/.env.local` にコピーして値を入れます（README の「開発環境の構築手順」）。値は CloudFormation の出力（`HttpApiUrl`・`StaffUserPoolClientId`）から取れます。
