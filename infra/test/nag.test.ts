import * as cdk from 'aws-cdk-lib';
import { Annotations, Match } from 'aws-cdk-lib/assertions';
import { AwsSolutionsChecks, NagSuppressions } from 'cdk-nag';
import { StatefulStack } from '../lib/stateful-stack';
import { AppStack } from '../lib/app-stack';

function buildStacks() {
  const app = new cdk.App();
  const env = { account: '123456789012', region: 'ap-northeast-1' };
  const stateful = new StatefulStack(app, 'NagStateful', { stage: 'dev', env });
  const appStack = new AppStack(app, 'NagApp', { stage: 'dev', env, table: stateful.table });

  cdk.Aspects.of(stateful).add(new AwsSolutionsChecks());
  cdk.Aspects.of(appStack).add(new AwsSolutionsChecks());

  const appPath = appStack.node.path;

  // Lambda基本実行ロール(AWSLambdaBasicExecutionRole)はCDKの既定付与。
  // Menu/CartFnのServiceRoleのみに限定し、将来追加される他リソースのIAM4違反は隠さない。
  NagSuppressions.addResourceSuppressionsByPath(
    appStack,
    [
      `${appPath}/MenuFn/ServiceRole/Resource`,
      `${appPath}/CartFn/ServiceRole/Resource`,
    ],
    [
      {
        id: 'AwsSolutions-IAM4',
        reason: 'AWSLambdaBasicExecutionRoleはCDKが自動付与する既定の管理ポリシー。',
        appliesTo: ['Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'],
      },
    ],
  );

  // X-Ray書き込み(xray:PutTraceSegments等)はAWS仕様上リソースレベル権限に対応しておらず
  // Resource:"*"が必須。dynamodb.Table.grantReadData()/grantReadWriteData()が生成する
  // "<tableArn>/index/*"はテーブル本体+GSIへのアクセスのみにスコープされた想定内パターン。
  // Menu/CartFnのDefaultPolicyのみに限定する。
  NagSuppressions.addResourceSuppressionsByPath(
    appStack,
    [
      `${appPath}/MenuFn/ServiceRole/DefaultPolicy/Resource`,
      `${appPath}/CartFn/ServiceRole/DefaultPolicy/Resource`,
    ],
    [
      {
        id: 'AwsSolutions-IAM5',
        reason:
          'X-Ray書き込み(xray:PutTraceSegments/PutTelemetryRecords)はAWS仕様上Resource:"*"が必須。'
          + 'DynamoDBアクセスはgrantReadData()/grantReadWriteData()が生成する<tableArn>/index/*のみにスコープ済み。',
        appliesTo: [
          'Resource::*',
          { regex: '/\\/index\\/\\*$/' },
        ],
      },
    ],
  );

  // ランタイムバージョン固定はMenu/CartFn自体のみに限定。
  NagSuppressions.addResourceSuppressionsByPath(
    appStack,
    [
      `${appPath}/MenuFn/Resource`,
      `${appPath}/CartFn/Resource`,
    ],
    [
      {
        id: 'AwsSolutions-L1',
        reason:
          'Powertools Lambda Layer(AWSLambdaPowertoolsPythonV3-Arm64)がPython3.12ビルドのため、'
          + 'ランタイムをPython3.12に意図的に固定している。Layer側の対応バージョン更新と合わせて上げる。',
      },
    ],
  );

  // アクセスログ未設定はDefaultStageのみに限定。
  NagSuppressions.addResourceSuppressionsByPath(
    appStack,
    `${appPath}/DefaultStage/Resource`,
    [
      {
        id: 'AwsSolutions-APIG1',
        reason: 'menu-fn/cart-fn疎通確認用の最小スライス。アクセスログは運用整備フェーズで有効化する。',
      },
    ],
  );

  // 認証なしはmenu-fn(2ルート)・cart-fn(4ルート)のみに限定。将来追加する未認証ルートのAPIG4違反は隠さない。
  NagSuppressions.addResourceSuppressionsByPath(
    appStack,
    [
      `${appPath}/HttpApi/GET--menu/Resource`,
      `${appPath}/HttpApi/GET--menu--{productId}/Resource`,
      `${appPath}/HttpApi/GET--cart--{sessionId}/Resource`,
      `${appPath}/HttpApi/POST--cart--{sessionId}--items/Resource`,
      `${appPath}/HttpApi/PUT--cart--{sessionId}--items--{itemId}/Resource`,
      `${appPath}/HttpApi/DELETE--cart--{sessionId}--items--{itemId}/Resource`,
    ],
    [
      {
        id: 'AwsSolutions-APIG4',
        reason:
          'menu-fn/cart-fnは認証不要の公開エンドポイント（要件定義上、顧客向けメニュー・カート操作APIは'
          + 'sessionIdのみで識別しCognito認証を要求しない、MVPの既定方針）。',
      },
    ],
  );

  return { stateful, appStack };
}

describe('cdk-nag AwsSolutionsChecks', () => {
  test('StatefulStack/AppStackともにError findingsが0件', () => {
    const { stateful, appStack } = buildStacks();

    const statefulErrors = Annotations.fromStack(stateful).findError(
      '*',
      Match.stringLikeRegexp('AwsSolutions-.*'),
    );
    const appErrors = Annotations.fromStack(appStack).findError(
      '*',
      Match.stringLikeRegexp('AwsSolutions-.*'),
    );

    if (statefulErrors.length > 0 || appErrors.length > 0) {
      // eslint-disable-next-line no-console
      console.error(
        'cdk-nag violations:',
        JSON.stringify([...statefulErrors, ...appErrors].map((e) => e.entry.data), null, 2),
      );
    }

    expect(statefulErrors).toHaveLength(0);
    expect(appErrors).toHaveLength(0);
  });
});
