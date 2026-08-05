import * as cdk from 'aws-cdk-lib';
import * as apigwv2 from 'aws-cdk-lib/aws-apigatewayv2';
import * as integrations from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import { PythonLambdaFunction } from './constructs/python-lambda-function';
import { StageStackProps } from './stateful-stack';

export interface AppStackProps extends StageStackProps {
  readonly table: dynamodb.Table;
}

/**
 * スライス①（menu-fn）＋スライス②（cart-fn）＋スライス③（order-fn/status-fn）を配線したapp-stack。
 * store/WebSocket/SQS/EventBridge/Cognito/ConnectionTable/payment-fnは対象外。
 */
export class AppStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: AppStackProps) {
    super(scope, id, props);

    const menuFn = new PythonLambdaFunction(this, 'MenuFn', {
      functionName: `MobileOrder-${props.stage}-menu-fn`,
      handler: 'handlers.menu.handler',
      environment: { TABLE_NAME: props.table.tableName },
    });
    props.table.grantReadData(menuFn);

    const cartFn = new PythonLambdaFunction(this, 'CartFn', {
      functionName: `MobileOrder-${props.stage}-cart-fn`,
      handler: 'handlers.cart.handler',
      environment: { TABLE_NAME: props.table.tableName },
    });
    // cart-fnはCART行の読み書きに加え、商品検証のためMENU行の読み取りも行う(単一テーブル設計)。
    props.table.grantReadWriteData(cartFn);

    const orderFn = new PythonLambdaFunction(this, 'OrderFn', {
      functionName: `MobileOrder-${props.stage}-order-fn`,
      handler: 'handlers.order.handler',
      environment: { TABLE_NAME: props.table.tableName },
    });
    // order-fnはORDER/LINE/ZONESEQ/ORDERNUM/IDEMPOTENCYの書き込み＋CART削除＋MENU読み取りを行う
    // (単一テーブル設計。書き込み範囲がcart-fnより広いが同じgrantReadWriteData()で足りる)。
    props.table.grantReadWriteData(orderFn);
    // dynamodb:TransactWriteItemsはgrantReadWriteData()には含まれない独立したIAMアクションのため、
    // adapters/order_repository.pyのcreate_order/cancel_order(TransactWriteItems使用)向けに
    // 個別に付与する(mote上のテストではIAM検証が行われないため、この不足はcdk-nag/実デプロイでしか
    // 気づけない)。
    orderFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['dynamodb:TransactWriteItems'],
      resources: [props.table.tableArn],
    }));

    const statusFn = new PythonLambdaFunction(this, 'StatusFn', {
      functionName: `MobileOrder-${props.stage}-status-fn`,
      handler: 'handlers.status.handler',
      environment: { TABLE_NAME: props.table.tableName },
      // ポーリング専用の読み取りLambdaのためINFOログを抑え、ロググループも短期保持にして
      // CloudWatch Logsコストを抑える(todo.md §1③のインフラタスク、architectの指摘)。
      logLevel: 'WARNING',
      logRetentionDays: props.stage === 'prod' ? 14 : 7,
    });
    props.table.grantReadData(statusFn);

    const httpApi = new apigwv2.HttpApi(this, 'HttpApi', {
      apiName: `MobileOrder-${props.stage}-http-api`,
      // デフォルトステージをスロットル設定付きで自前定義するため、自動作成を無効化する。
      createDefaultStage: false,
    });

    // 公開エンドポイント（認証なし）にバースト/レート上限を設定し、過負荷・濫用を防ぐ。
    const defaultStage = new apigwv2.HttpStage(this, 'DefaultStage', {
      httpApi,
      autoDeploy: true,
      throttle: { rateLimit: 50, burstLimit: 100 },
    });

    const menuIntegration = new integrations.HttpLambdaIntegration('MenuIntegration', menuFn);
    httpApi.addRoutes({
      path: '/menu',
      methods: [apigwv2.HttpMethod.GET],
      integration: menuIntegration,
    });
    httpApi.addRoutes({
      path: '/menu/{productId}',
      methods: [apigwv2.HttpMethod.GET],
      integration: menuIntegration,
    });

    const cartIntegration = new integrations.HttpLambdaIntegration('CartIntegration', cartFn);
    httpApi.addRoutes({
      path: '/cart/{sessionId}',
      methods: [apigwv2.HttpMethod.GET],
      integration: cartIntegration,
    });
    httpApi.addRoutes({
      path: '/cart/{sessionId}/items',
      methods: [apigwv2.HttpMethod.POST],
      integration: cartIntegration,
    });
    httpApi.addRoutes({
      path: '/cart/{sessionId}/items/{itemId}',
      methods: [apigwv2.HttpMethod.PUT],
      integration: cartIntegration,
    });
    httpApi.addRoutes({
      path: '/cart/{sessionId}/items/{itemId}',
      methods: [apigwv2.HttpMethod.DELETE],
      integration: cartIntegration,
    });

    const orderIntegration = new integrations.HttpLambdaIntegration('OrderIntegration', orderFn);
    const createOrderRoutes = httpApi.addRoutes({
      path: '/orders',
      methods: [apigwv2.HttpMethod.POST],
      integration: orderIntegration,
    });
    const cancelOrderRoutes = httpApi.addRoutes({
      path: '/orders/{orderId}/cancel',
      methods: [apigwv2.HttpMethod.PATCH],
      integration: orderIntegration,
    });

    const statusIntegration = new integrations.HttpLambdaIntegration(
      'StatusIntegration',
      statusFn,
    );
    const getOrderStatusRoutes = httpApi.addRoutes({
      path: '/orders/{orderId}',
      methods: [apigwv2.HttpMethod.GET],
      integration: statusIntegration,
    });
    const getQueuePositionRoutes = httpApi.addRoutes({
      path: '/orders/{orderId}/queue-position',
      methods: [apigwv2.HttpMethod.GET],
      integration: statusIntegration,
    });

    // per-routeスロットリング(ステージ全体の既定50/100の上に、ルート別の上限を上書きする)。
    // HttpStageのL2はルート別設定を公開していないため、L1(CfnStage)のエスケープハッチで設定する
    // (計画の小さな決定#6)。ポーリング暴走が書き込み系(POST /orders等)を巻き添えにしないよう、
    // 読み取り系(status-fn)と書き込み系(order-fn)を別バケットに分離する。
    // `routeSettings`propは型付けされていない生のCFNプロパティ(`any`)のため、L2の他propと違って
    // camelCase→PascalCaseの自動変換が効かない。CFNのプロパティ名(PascalCase)をそのまま書く必要がある。
    const cfnDefaultStage = defaultStage.node.defaultChild as apigwv2.CfnStage;
    cfnDefaultStage.routeSettings = {
      'GET /orders/{orderId}': { ThrottlingRateLimit: 50, ThrottlingBurstLimit: 100 },
      'GET /orders/{orderId}/queue-position': { ThrottlingRateLimit: 50, ThrottlingBurstLimit: 100 },
      'POST /orders': { ThrottlingRateLimit: 20, ThrottlingBurstLimit: 40 },
      'PATCH /orders/{orderId}/cancel': { ThrottlingRateLimit: 20, ThrottlingBurstLimit: 40 },
    };
    // routeSettingsは文字列キーで対象ルートを指定するだけでCFN参照(Ref/Fn::GetAtt)を持たないため、
    // CDKは「Stageがこれらのルートに依存する」ことを自動認識できない。明示的にDependsOnを追加しないと、
    // CloudFormationがRoute作成前にStage更新を実行してしまい「Unable to find Route by key」で
    // 失敗する(実デプロイで発覚。cdk synthの静的検証だけでは検出できないクラスの不備だった)。
    for (const route of [
      ...createOrderRoutes,
      ...cancelOrderRoutes,
      ...getOrderStatusRoutes,
      ...getQueuePositionRoutes,
    ]) {
      cfnDefaultStage.node.addDependency(route);
    }

    new cdk.CfnOutput(this, 'HttpApiUrl', {
      value: httpApi.apiEndpoint,
      exportName: `MobileOrder-${props.stage}-HttpApiUrl`,
    });
  }
}
