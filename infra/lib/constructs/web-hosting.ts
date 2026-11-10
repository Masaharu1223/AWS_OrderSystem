import * as cdk from 'aws-cdk-lib';
import * as amplify from 'aws-cdk-lib/aws-amplify';
import { Construct } from 'constructs';
import { Stage } from '../stateful-stack';

export interface WebHostingProps {
  readonly stage: Stage;
  /** 例: "https://github.com/<owner>/<repo>" */
  readonly repositoryUrl: string;
  /** Amplifyがビルド・配信するGitブランチ(例: "main") */
  readonly branchName: string;
  /**
   * GitHubのpersonal access token(スコープ`admin:repo_hook`)を保存したSecrets Managerの
   * シークレット名。値はデプロイ前に手動で登録しておく(tasks/todo.md §36)。
   */
  readonly githubTokenSecretName: string;
}

export interface WebHostingBackendProps {
  /** ブラウザが呼ぶAPIのURL(末尾スラッシュなし)。NEXT_PUBLIC_API_BASE_URLとして埋め込まれる */
  readonly apiEndpoint: string;
  /** 店員ログイン(Cognito)のアプリクライアントID。NEXT_PUBLIC_STAFF_CLIENT_IDとして埋め込まれる */
  readonly staffUserPoolClientId: string;
}

/**
 * フロントエンド(web/)をAmplify Hostingで静的配信する(docs/architecture.md §1.3)。
 *
 * 役割:
 * - Amplifyアプリ(GitHubリポジトリと接続)と、配信するブランチ1本を作る。
 * - ビルド手順はリポジトリ直下のamplify.ymlで管理し、ここには書かない(二重管理を避ける)。
 *
 * 使い方は2段階になっている。APIのCORS設定には「フロントのURL」が要り、フロントのビルドには
 * 「APIのURL」が要るため、どちらかを先に決める必要があるからだ。
 *   1. `new WebHosting(...)` でAmplifyアプリを作る → `origin`(フロントのURL)が決まる
 *   2. `origin`をCORSに入れてHttpApiを作る
 *   3. `connectBackend(...)` でブランチを作り、APIのURL等をビルド時の環境変数として渡す
 * 同じスタック内なのでCloudFormation上の参照は一方向(API→App、Branch→API/App)で循環しない。
 *
 * 注意: このConstructのIDやブランチ名を変えるとAmplifyアプリが作り直され、URL(amplifyapp.com)が
 * 変わる。お店に貼るQRコード等にURLを使う前に、独自ドメインを用意すること。
 */
export class WebHosting extends Construct {
  /** ブラウザから見たフロントのURL(例: https://main.d1234.amplifyapp.com)。CORSの許可元に使う */
  public readonly origin: string;
  public readonly appId: string;

  private readonly app: amplify.CfnApp;
  private readonly props: WebHostingProps;

  constructor(scope: Construct, id: string, props: WebHostingProps) {
    super(scope, id);
    this.props = props;

    this.app = new amplify.CfnApp(this, 'App', {
      name: `MobileOrder-${props.stage}-web`,
      repository: props.repositoryUrl,
      // Amplifyはこのトークンを作成時にGitHub App経由の接続設定へ使うだけで保存しない。
      // テンプレートには`{{resolve:secretsmanager:...}}`という参照文字列だけが入り、値は
      // CloudFormationがデプロイ時に読む(unsafeUnwrapは「文字列として渡す」ためのAPI名で、
      // 平文がテンプレートに出るわけではない)。SSM SecureStringの動的参照はAccessTokenで
      // 使えないため、Secrets Managerを使う。
      accessToken: cdk.SecretValue.secretsManager(props.githubTokenSecretName).unsafeUnwrap(),
      // Next.jsを検出するとSSR(WEB_COMPUTE)扱いになることがある。web/は静的エクスポートなので
      // 静的配信(WEB)を明示する。
      platform: 'WEB',
      // モノレポのweb/だけをビルドする。amplify.ymlのappRootと一致させる必要がある
      // (コンソールで作ると自動設定されるが、CloudFormationで作る場合は自分で設定する)。
      // NEXT_PUBLIC_*はApp単位に置かないこと: App→HttpApi→App(CORS)で循環参照になる。
      environmentVariables: [{ name: 'AMPLIFY_MONOREPO_APP_ROOT', value: 'web' }],
    });

    this.appId = this.app.attrAppId;
    this.origin = `https://${props.branchName}.${this.app.attrDefaultDomain}`;
  }

  /**
   * 配信するブランチを作り、APIのURLと店員ログインのIDをビルド時の環境変数として渡す。
   *
   * NEXT_PUBLIC_*はビルド時にJSへ埋め込まれる。値が変わった(HttpApiの作り直し等)ときは、
   * Amplifyで再ビルド(`aws amplify start-job --job-type RELEASE`)しないとサイトに反映されない。
   */
  public connectBackend(backend: WebHostingBackendProps): amplify.CfnBranch {
    return new amplify.CfnBranch(this, 'Branch', {
      appId: this.app.attrAppId,
      branchName: this.props.branchName,
      framework: 'Next.js - SSG',
      // 今はdevでしか作らないが、prodを追加したときに正しい値になるようstageから決める。
      stage: this.props.stage === 'prod' ? 'PRODUCTION' : 'DEVELOPMENT',
      // pushで自動ビルド。PRごとのプレビュー環境はURLが毎回変わりCORSに載せられないため無効。
      enableAutoBuild: true,
      enablePullRequestPreview: false,
      environmentVariables: [
        { name: 'NEXT_PUBLIC_API_BASE_URL', value: backend.apiEndpoint },
        { name: 'NEXT_PUBLIC_STAFF_CLIENT_ID', value: backend.staffUserPoolClientId },
      ],
    });
  }
}
