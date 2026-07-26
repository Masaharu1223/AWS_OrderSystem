import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { StatefulStack } from '../lib/stateful-stack';
import { AppStack } from '../lib/app-stack';

describe('AppStack', () => {
  const app = new cdk.App();
  const env = { account: '123456789012', region: 'ap-northeast-1' };
  const stateful = new StatefulStack(app, 'TestStateful2', { stage: 'dev', env });
  const stack = new AppStack(app, 'TestApp', { stage: 'dev', env, table: stateful.table });
  const template = Template.fromStack(stack);

  test('menu-fn LambdaがPython3.12/arm64・正しいハンドラ文字列・Powertools Layer1個を持つ', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'MobileOrder-dev-menu-fn',
      Runtime: 'python3.12',
      Architectures: ['arm64'],
      Handler: 'handlers.menu.handler',
      Environment: {
        Variables: Match.objectLike({
          POWERTOOLS_SERVICE_NAME: 'MobileOrder-dev-menu-fn',
        }),
      },
    });
    template.resourceCountIs('AWS::Lambda::Function', 1);

    const fns = template.findResources('AWS::Lambda::Function');
    const menuFn = Object.values(fns)[0] as { Properties: { Layers?: unknown[] } };
    expect(menuFn.Properties.Layers).toHaveLength(1);
  });

  test('HTTP APIに GET /menu と GET /menu/{productId} の2ルートが同一Lambda統合で存在する', () => {
    template.resourceCountIs('AWS::ApiGatewayV2::Api', 1);
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
      RouteKey: 'GET /menu',
    });
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
      RouteKey: 'GET /menu/{productId}',
    });
    template.resourceCountIs('AWS::ApiGatewayV2::Route', 2);
    template.resourceCountIs('AWS::ApiGatewayV2::Integration', 1);
  });

  test('menu-fnのIAMポリシー: X-Ray書き込み以外にResource="*"を持たず、DynamoDB権限は読み取り専用アクションのみでテーブル本体+GSI(index/*)の2件だけにスコープされる', () => {
    const policies = template.findResources('AWS::IAM::Policy');
    type Statement = { Action: unknown; Effect: string; Resource: unknown };
    const allStatements = Object.values(policies).flatMap(
      (p) => (p as { Properties: { PolicyDocument: { Statement: Statement[] } } }).Properties.PolicyDocument.Statement,
    );

    const dynamoStatements = allStatements.filter((stmt) => {
      const actions = Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action];
      return actions.some((a) => typeof a === 'string' && a.startsWith('dynamodb:'));
    });
    // grantReadData()はCDKの内部最適化でアクションを複数Statementに分割することがあるため、
    // Statement数ではなく「全dynamodb系Statementの内容」を検証する。
    expect(dynamoStatements.length).toBeGreaterThan(0);

    for (const stmt of dynamoStatements) {
      const actions = stmt.Action as string[];
      // 書き込み系アクション(PutItem/UpdateItem/DeleteItem/TransactWriteItems等)を含まないこと
      for (const action of actions) {
        expect(action).toMatch(/^dynamodb:(BatchGetItem|ConditionCheckItem|DescribeTable|GetItem|GetRecords|GetShardIterator|Query|Scan)$/);
      }
      const resources = stmt.Resource as unknown[];
      expect(resources).toHaveLength(2); // テーブル本体ARN + index/* の2件のみ
      expect(JSON.stringify(resources[1])).toMatch(/\/index\/\*/); // 2件目がGSIワイルドカード
    }

    for (const stmt of allStatements) {
      const actions2 = Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action];
      const isXrayWrite = actions2.every(
        (a) => a === 'xray:PutTraceSegments' || a === 'xray:PutTelemetryRecords',
      );
      if (isXrayWrite) continue; // X-Rayはリソースレベル権限未対応のためAWS仕様上「*」が必須
      const resources2 = Array.isArray(stmt.Resource) ? stmt.Resource : [stmt.Resource];
      for (const r of resources2) {
        if (typeof r === 'string') {
          expect(r).not.toBe('*');
        }
      }
    }
  });

  test('cart/order/status/store/WebSocket/SQS/EventBridge/Cognitoはこのスライスでは作られない', () => {
    template.resourceCountIs('AWS::Cognito::UserPool', 0);
    template.resourceCountIs('AWS::SQS::Queue', 0);
    template.resourceCountIs('AWS::Events::Rule', 0);
  });
});
