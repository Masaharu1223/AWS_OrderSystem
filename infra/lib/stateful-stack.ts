import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';

export type Stage = 'dev' | 'prod';

export interface StageStackProps extends cdk.StackProps {
  readonly stage: Stage;
}

export class StatefulStack extends cdk.Stack {
  public readonly table: dynamodb.Table;

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
  }
}
