import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { StatefulStack } from '../lib/stateful-stack';
import { AppStack } from '../lib/app-stack';

describe('AppStack', () => {
  const app = new cdk.App();
  const env = { account: '123456789012', region: 'ap-northeast-1' };
  const stateful = new StatefulStack(app, 'TestStateful2', { stage: 'dev', env });
  const stack = new AppStack(app, 'TestApp', {
    stage: 'dev',
    env,
    table: stateful.table,
    staffUserPool: stateful.staffUserPool,
    staffUserPoolClient: stateful.staffUserPoolClient,
  });
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

    const fns = template.findResources('AWS::Lambda::Function');
    const menuFn = Object.values(fns).find(
      (f) => (f as { Properties: { FunctionName?: string } }).Properties.FunctionName
        === 'MobileOrder-dev-menu-fn',
    ) as { Properties: { Layers?: unknown[] } };
    expect(menuFn.Properties.Layers).toHaveLength(1);
  });

  test('cart-fn LambdaがPython3.12/arm64・正しいハンドラ文字列・Powertools Layer1個を持つ', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'MobileOrder-dev-cart-fn',
      Runtime: 'python3.12',
      Architectures: ['arm64'],
      Handler: 'handlers.cart.handler',
      Environment: {
        Variables: Match.objectLike({
          POWERTOOLS_SERVICE_NAME: 'MobileOrder-dev-cart-fn',
        }),
      },
    });

    const fns = template.findResources('AWS::Lambda::Function');
    const cartFn = Object.values(fns).find(
      (f) => (f as { Properties: { FunctionName?: string } }).Properties.FunctionName
        === 'MobileOrder-dev-cart-fn',
    ) as { Properties: { Layers?: unknown[] } };
    expect(cartFn.Properties.Layers).toHaveLength(1);
  });

  test('order-fn LambdaがPython3.12/arm64・正しいハンドラ文字列・Powertools Layer1個を持つ', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'MobileOrder-dev-order-fn',
      Runtime: 'python3.12',
      Architectures: ['arm64'],
      Handler: 'handlers.order.handler',
      Environment: {
        Variables: Match.objectLike({
          POWERTOOLS_SERVICE_NAME: 'MobileOrder-dev-order-fn',
        }),
      },
    });

    const fns = template.findResources('AWS::Lambda::Function');
    const orderFn = Object.values(fns).find(
      (f) => (f as { Properties: { FunctionName?: string } }).Properties.FunctionName
        === 'MobileOrder-dev-order-fn',
    ) as { Properties: { Layers?: unknown[] } };
    expect(orderFn.Properties.Layers).toHaveLength(1);
  });

  test('status-fn LambdaがPython3.12/arm64・正しいハンドラ文字列・LOG_LEVEL=WARNINGを持つ', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'MobileOrder-dev-status-fn',
      Runtime: 'python3.12',
      Architectures: ['arm64'],
      Handler: 'handlers.status.handler',
      Environment: {
        Variables: Match.objectLike({
          POWERTOOLS_SERVICE_NAME: 'MobileOrder-dev-status-fn',
          LOG_LEVEL: 'WARNING',
        }),
      },
    });
  });

  test('status-fnのロググループはdevで7日保持', () => {
    template.hasResourceProperties('AWS::Logs::LogGroup', {
      LogGroupName: '/aws/lambda/MobileOrder-dev-status-fn',
      RetentionInDays: 7,
    });
  });

  test('store-fn LambdaがPython3.12/arm64・正しいハンドラ文字列・Powertools Layer1個を持つ', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'MobileOrder-dev-store-fn',
      Runtime: 'python3.12',
      Architectures: ['arm64'],
      Handler: 'handlers.store.handler',
      Environment: {
        Variables: Match.objectLike({
          POWERTOOLS_SERVICE_NAME: 'MobileOrder-dev-store-fn',
          HANDOVER_API_KEY_PARAMETER_NAME: '/mobile-order/dev/handover-api-key',
        }),
      },
    });

    const fns = template.findResources('AWS::Lambda::Function');
    const storeFn = Object.values(fns).find(
      (f) => (f as { Properties: { FunctionName?: string } }).Properties.FunctionName
        === 'MobileOrder-dev-store-fn',
    ) as { Properties: { Layers?: unknown[] } };
    expect(storeFn.Properties.Layers).toHaveLength(1);
  });

  test('Lambda関数はmenu-fn/cart-fn/order-fn/status-fn/store-fnの5個のみ', () => {
    template.resourceCountIs('AWS::Lambda::Function', 5);
  });

  test('HTTP APIに menu-fn 2 + cart-fn 4 + order-fn 2 + status-fn 2 + store-fn 3 = 13ルートが存在する', () => {
    template.resourceCountIs('AWS::ApiGatewayV2::Api', 1);
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', { RouteKey: 'GET /menu' });
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
      RouteKey: 'GET /menu/{productId}',
    });
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
      RouteKey: 'GET /cart/{sessionId}',
    });
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
      RouteKey: 'POST /cart/{sessionId}/items',
    });
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
      RouteKey: 'PUT /cart/{sessionId}/items/{itemId}',
    });
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
      RouteKey: 'DELETE /cart/{sessionId}/items/{itemId}',
    });
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', { RouteKey: 'POST /orders' });
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
      RouteKey: 'PATCH /orders/{orderId}/cancel',
    });
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
      RouteKey: 'GET /orders/{orderId}',
    });
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
      RouteKey: 'GET /orders/{orderId}/queue-position',
    });
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
      RouteKey: 'GET /stores/{storeId}/zones/{zone}/lines',
    });
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
      RouteKey: 'PATCH /orders/{orderId}/lines/{lineId}/status',
    });
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
      RouteKey: 'PATCH /orders/{orderId}/lines/{lineId}/handover',
    });
    template.resourceCountIs('AWS::ApiGatewayV2::Route', 13);
    // menu-fn用1個 + cart-fn用1個(4ルートで共有) + order-fn用1個(2ルートで共有)
    // + status-fn用1個(2ルートで共有) + store-fn用1個(3ルートで共有)の5個
    template.resourceCountIs('AWS::ApiGatewayV2::Integration', 5);
  });

  test('店員向け2ルート(一覧・状態更新)はJWTオーソライザーを持ち、受渡検知ルートは持たない', () => {
    template.resourceCountIs('AWS::ApiGatewayV2::Authorizer', 1);
    template.hasResourceProperties('AWS::ApiGatewayV2::Authorizer', {
      AuthorizerType: 'JWT',
    });

    const authorizers = template.findResources('AWS::ApiGatewayV2::Authorizer');
    const authorizerLogicalId = Object.keys(authorizers)[0];

    template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
      RouteKey: 'GET /stores/{storeId}/zones/{zone}/lines',
      AuthorizationType: 'JWT',
      AuthorizerId: { Ref: authorizerLogicalId },
    });
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
      RouteKey: 'PATCH /orders/{orderId}/lines/{lineId}/status',
      AuthorizationType: 'JWT',
      AuthorizerId: { Ref: authorizerLogicalId },
    });
    template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
      RouteKey: 'PATCH /orders/{orderId}/lines/{lineId}/handover',
      AuthorizationType: 'NONE',
      AuthorizerId: Match.absent(),
    });
  });

  test('HttpApiがCORS設定を持つ(web/の静的エクスポート移行に伴いブラウザから直接叩かれるため。'
    + 'AuthorizationはCognito JWTを送るために必要)', () => {
    template.hasResourceProperties('AWS::ApiGatewayV2::Api', {
      CorsConfiguration: {
        AllowOrigins: ['http://localhost:3000'],
        AllowMethods: Match.arrayWith(['GET', 'POST', 'PUT', 'DELETE', 'PATCH']),
        AllowHeaders: Match.arrayWith(['Content-Type', 'Idempotency-Key', 'Authorization']),
      },
    });
  });

  test('DefaultStageのRouteSettingsでポーリング系(status-fn)と書き込み系(order-fn)が別バケットに分離されている', () => {
    template.hasResourceProperties('AWS::ApiGatewayV2::Stage', {
      RouteSettings: {
        'GET /orders/{orderId}': { ThrottlingRateLimit: 50, ThrottlingBurstLimit: 100 },
        'GET /orders/{orderId}/queue-position': {
          ThrottlingRateLimit: 50,
          ThrottlingBurstLimit: 100,
        },
        'POST /orders': { ThrottlingRateLimit: 20, ThrottlingBurstLimit: 40 },
        'PATCH /orders/{orderId}/cancel': { ThrottlingRateLimit: 20, ThrottlingBurstLimit: 40 },
        'GET /stores/{storeId}/zones/{zone}/lines': {
          ThrottlingRateLimit: 50,
          ThrottlingBurstLimit: 100,
        },
        'PATCH /orders/{orderId}/lines/{lineId}/status': {
          ThrottlingRateLimit: 20,
          ThrottlingBurstLimit: 40,
        },
        'PATCH /orders/{orderId}/lines/{lineId}/handover': {
          ThrottlingRateLimit: 20,
          ThrottlingBurstLimit: 40,
        },
      },
    });
  });

  type Statement = { Action: unknown; Effect: string; Resource: unknown };

  // 指定した関数名(FunctionName)のLambdaにアタッチされたDefaultPolicyのStatement一覧を返す。
  // Lambdaの`Role`(Fn::GetAtt)からRoleの論理IDを辿り、`Roles`にそれを含むIAM::Policyを探すことで、
  // 関数が複数になっても取り違えずにスコープする。
  function policyStatementsFor(functionName: string): Statement[] {
    const fns = template.findResources('AWS::Lambda::Function');
    const fnEntry = Object.values(fns).find(
      (f) => (f as { Properties: { FunctionName?: string } }).Properties.FunctionName === functionName,
    ) as { Properties: { Role: { 'Fn::GetAtt': [string, string] } } };
    const roleLogicalId = fnEntry.Properties.Role['Fn::GetAtt'][0];

    const policies = template.findResources('AWS::IAM::Policy');
    const matching = Object.values(policies).filter((p) => {
      const roles = (p as { Properties: { Roles: unknown[] } }).Properties.Roles;
      return roles.some((r) => (r as { Ref?: string }).Ref === roleLogicalId);
    }) as { Properties: { PolicyDocument: { Statement: Statement[] } } }[];
    return matching.flatMap((p) => p.Properties.PolicyDocument.Statement);
  }

  function expectDynamoActionsMatch(statements: Statement[], allowedActionsPattern: RegExp) {
    const dynamoStatements = statements.filter((stmt) => {
      const actions = Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action];
      const isDynamoAction = actions.some((a) => typeof a === 'string' && a.startsWith('dynamodb:'));
      // dynamodb:TransactWriteItemsはgrantReadWriteData()由来のCRUD統一パターン(テーブル本体+GSIの
      // 2件)とは別に、テーブル本体のみにスコープした専用statementとして付与している(GSIを対象にしない
      // ため)。ここでは対象外にし、専用のテストで別途検証する。
      const isTransactWriteOnly = actions.length === 1 && actions[0] === 'dynamodb:TransactWriteItems';
      return isDynamoAction && !isTransactWriteOnly;
    });
    // grant*Data()はCDKの内部最適化でアクションを複数Statementに分割することがあるため、
    // Statement数ではなく「全dynamodb系Statementの内容」を検証する。
    expect(dynamoStatements.length).toBeGreaterThan(0);

    for (const stmt of dynamoStatements) {
      const actions = stmt.Action as string[];
      for (const action of actions) {
        expect(action).toMatch(allowedActionsPattern);
      }
      const resources = stmt.Resource as unknown[];
      expect(resources).toHaveLength(2); // テーブル本体ARN + index/* の2件のみ
      expect(JSON.stringify(resources[1])).toMatch(/\/index\/\*/); // 2件目がGSIワイルドカード
    }
  }

  test('menu-fnのIAMポリシー: DynamoDB権限は読み取り専用アクションのみでテーブル本体+GSI(index/*)の2件だけにスコープされる', () => {
    expectDynamoActionsMatch(
      policyStatementsFor('MobileOrder-dev-menu-fn'),
      /^dynamodb:(BatchGetItem|ConditionCheckItem|DescribeTable|GetItem|GetRecords|GetShardIterator|Query|Scan)$/,
    );
  });

  test('cart-fnのIAMポリシー: DynamoDB権限は読み書き両方のアクションを含み、それでもテーブル本体+GSI(index/*)の2件だけにスコープされる(ワイルドカードなし)', () => {
    expectDynamoActionsMatch(
      policyStatementsFor('MobileOrder-dev-cart-fn'),
      /^dynamodb:(BatchGetItem|BatchWriteItem|ConditionCheckItem|DeleteItem|DescribeTable|GetItem|GetRecords|GetShardIterator|PutItem|Query|Scan|UpdateItem)$/,
    );
  });

  test('order-fnのIAMポリシー: grantReadWriteData由来のCRUDアクションはテーブル本体+GSI(index/*)の2件だけにスコープされる', () => {
    expectDynamoActionsMatch(
      policyStatementsFor('MobileOrder-dev-order-fn'),
      /^dynamodb:(BatchGetItem|BatchWriteItem|ConditionCheckItem|DeleteItem|DescribeTable|GetItem|GetRecords|GetShardIterator|PutItem|Query|Scan|UpdateItem)$/,
    );
  });

  test('order-fnのIAMポリシー: dynamodb:TransactWriteItemsをテーブル本体のみ(GSIワイルドカードなし)の1件に個別付与している', () => {
    const statements = policyStatementsFor('MobileOrder-dev-order-fn');
    const transactWriteStatement = statements.find((stmt) => {
      const actions = Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action];
      return actions.length === 1 && actions[0] === 'dynamodb:TransactWriteItems';
    });

    expect(transactWriteStatement).toBeDefined();
    const resources = Array.isArray(transactWriteStatement!.Resource)
      ? transactWriteStatement!.Resource
      : [transactWriteStatement!.Resource];
    // TransactWriteItemsはGSIを対象にしないため、grantReadWriteData()の2件パターン(テーブル+index/*)
    // とは異なりテーブル本体1件だけにスコープされる。
    expect(resources).toHaveLength(1);
    expect(JSON.stringify(resources[0])).not.toMatch(/\/index\/\*/);
  });

  test('status-fnのIAMポリシー: DynamoDB権限は読み取り専用アクションのみでテーブル本体+GSI(index/*)の2件だけにスコープされる', () => {
    expectDynamoActionsMatch(
      policyStatementsFor('MobileOrder-dev-status-fn'),
      /^dynamodb:(BatchGetItem|ConditionCheckItem|DescribeTable|GetItem|GetRecords|GetShardIterator|Query|Scan)$/,
    );
  });

  test('store-fnのIAMポリシー: grantReadWriteData由来のCRUDアクションはテーブル本体+GSI(index/*)の2件だけにスコープされる(TransactWriteItemsは付与しない)', () => {
    expectDynamoActionsMatch(
      policyStatementsFor('MobileOrder-dev-store-fn'),
      /^dynamodb:(BatchGetItem|BatchWriteItem|ConditionCheckItem|DeleteItem|DescribeTable|GetItem|GetRecords|GetShardIterator|PutItem|Query|Scan|UpdateItem)$/,
    );

    const statements = policyStatementsFor('MobileOrder-dev-store-fn');
    const transactWriteStatement = statements.find((stmt) => {
      const actions = Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action];
      return actions.includes('dynamodb:TransactWriteItems');
    });
    expect(transactWriteStatement).toBeUndefined();
  });

  test('store-fnのIAMポリシー: SSM GetParameter系は受渡検知の合言葉1パラメータだけにスコープされる', () => {
    const statements = policyStatementsFor('MobileOrder-dev-store-fn');
    const ssmStatement = statements.find((stmt) => {
      const actions = Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action];
      return actions.some((a) => typeof a === 'string' && a.startsWith('ssm:'));
    });

    expect(ssmStatement).toBeDefined();
    const actions = Array.isArray(ssmStatement!.Action) ? ssmStatement!.Action : [ssmStatement!.Action];
    for (const action of actions) {
      expect(action).toMatch(/^ssm:(DescribeParameters|GetParameter|GetParameterHistory|GetParameters)$/);
    }
    const resources = Array.isArray(ssmStatement!.Resource)
      ? ssmStatement!.Resource
      : [ssmStatement!.Resource];
    expect(resources).toHaveLength(1);
    expect(JSON.stringify(resources[0])).toMatch(/handover-api-key/);
  });

  test('X-Ray書き込み以外、どのIAMポリシーもResource="*"を持たない', () => {
    const policies = template.findResources('AWS::IAM::Policy');
    const allStatements = Object.values(policies).flatMap(
      (p) => (p as { Properties: { PolicyDocument: { Statement: Statement[] } } }).Properties.PolicyDocument.Statement,
    );

    for (const stmt of allStatements) {
      const actions = Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action];
      const isXrayWrite = actions.every(
        (a) => a === 'xray:PutTraceSegments' || a === 'xray:PutTelemetryRecords',
      );
      if (isXrayWrite) continue; // X-Rayはリソースレベル権限未対応のためAWS仕様上「*」が必須
      const resources = Array.isArray(stmt.Resource) ? stmt.Resource : [stmt.Resource];
      for (const r of resources) {
        if (typeof r === 'string') {
          expect(r).not.toBe('*');
        }
      }
    }
  });

  test('WebSocket/SQS/EventBridgeはMVPスコープ外のためapp-stackには作られない(CognitoはStatefulStack側に作る、stateful-stack.test.ts参照)', () => {
    template.resourceCountIs('AWS::Cognito::UserPool', 0);
    template.resourceCountIs('AWS::SQS::Queue', 0);
    template.resourceCountIs('AWS::Events::Rule', 0);
  });
});
