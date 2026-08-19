import * as cdk from 'aws-cdk-lib';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';

export type Stage = 'dev' | 'prod';

export interface StageStackProps extends cdk.StackProps {
  readonly stage: Stage;
}

export class StatefulStack extends cdk.Stack {
  public readonly table: dynamodb.Table;
  public readonly staffUserPool: cognito.UserPool;
  public readonly staffUserPoolClient: cognito.UserPoolClient;

  constructor(scope: Construct, id: string, props: StageStackProps) {
    // ステートフルなリソース（DynamoDBテーブル本体）を持つスタックのため、
    // 誤った`cdk destroy`/スタック削除操作からの保護としてCFN終了保護を有効化する。
    super(scope, id, { ...props, terminationProtection: true });

    this.table = new dynamodb.Table(this, 'MobileOrderTable', {
      // 物理名は明示せずCDK/CFNに自動生成させる（論理名`MobileOrderTable`が正、
      // 物理名はLambdaへ環境変数`TABLE_NAME`として注入する契約 — docs/requirements.md §11.3）。
      // 明示的な物理名固定は、置換が必要なプロパティ変更時にCFNが新旧リソースを
      // 同時存在させられず更新に失敗する原因になるため避ける。
      partitionKey: { name: 'PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'SK', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      deletionProtection: true,
      // テーブル全体で共有する単一のTTL属性(docs/architecture.md §6.1)。
      // cart-fnのカート明細が最初に使い、将来IDEMPOTENCY/ORDERNUMも同じ属性名に載せる。
      timeToLiveAttribute: 'expiresAt',
    });

    // GSI1: 店舗のステータス別注文一覧
    this.table.addGlobalSecondaryIndex({
      indexName: 'GSI1',
      partitionKey: { name: 'GSI1PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'GSI1SK', type: dynamodb.AttributeType.STRING },
    });

    // GSI2: ゾーン別製造キュー（WAITING/PREPARINGのみ保持するスパースインデックス）
    this.table.addGlobalSecondaryIndex({
      indexName: 'GSI2',
      partitionKey: { name: 'GSI2PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'GSI2SK', type: dynamodb.AttributeType.NUMBER },
    });

    // 店員さん向けログイン(store-fn)。ログイン情報はテーブルと同じ「消してはいけない」グループのため
    // このスタックに置く(app-stackではない)。共有アカウント運用のためセルフサインアップは無効にし、
    // アカウント自体はCDKで作らずデプロイ後に手動作成する(docs/requirements.md)。
    this.staffUserPool = new cognito.UserPool(this, 'StaffUserPool', {
      userPoolName: `MobileOrder-${props.stage}-staff-user-pool`,
      selfSignUpEnabled: false,
      signInAliases: { username: true },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      deletionProtection: true,
      // cdk-nag AwsSolutions-COG1対応。CDKの既定値は記号を必須にしないため明示的に指定する。
      passwordPolicy: {
        minLength: 8,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
      },
    });

    this.staffUserPoolClient = this.staffUserPool.addClient('StaffUserPoolClient', {
      // 当初はuserSrp(ブラウザ用)+adminUserPassword(IAM権限必須、curl確認用)の構成だったが、
      // ブラウザ実装フェーズでarchitectと再検討し、USER_PASSWORD_AUTHへ一本化した。
      // 守る対象がドリンクの製造ステータスのみ(金銭・個人情報を含まない)で、共有アカウント1つ・
      // 店内タブレット限定という脅威モデル上、SRP採用=SRPライブラリ導入(100〜190KB)のコストに
      // 見合わないと判断(tasks/todo.md §31)。USER_PASSWORD_AUTHはIAM権限不要でaws-cliからの
      // 動作確認もそのまま行えるため、admin-initiate-auth用のadminUserPasswordは不要になった。
      authFlows: { userPassword: true },
      // 共有・持ち出し可能なタブレットのため、既定の30日は紛失時の被害windowが長すぎる。
      // シフト単位の運用に合わせて1日に短縮(新規発行分のみ反映、既存トークンには遡及しない)。
      refreshTokenValidity: cdk.Duration.days(1),
    });

    // デプロイ後の手動作業(共有アカウント作成・動作確認用ログイン)で必要になるIDをCFN Outputsとして
    // 出力しておく(app-stack.tsのHttpApiUrlと同じ理由。コンソールを探さずコピペで使えるようにする)。
    new cdk.CfnOutput(this, 'StaffUserPoolId', {
      value: this.staffUserPool.userPoolId,
      exportName: `MobileOrder-${props.stage}-StaffUserPoolId`,
    });
    new cdk.CfnOutput(this, 'StaffUserPoolClientId', {
      value: this.staffUserPoolClient.userPoolClientId,
      exportName: `MobileOrder-${props.stage}-StaffUserPoolClientId`,
    });
  }
}
