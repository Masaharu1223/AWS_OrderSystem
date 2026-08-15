import * as cdk from 'aws-cdk-lib';
import * as apigwv2 from 'aws-cdk-lib/aws-apigatewayv2';
import * as authorizers from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import * as integrations from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';
import { PythonLambdaFunction } from './constructs/python-lambda-function';
import { StageStackProps } from './stateful-stack';

export interface AppStackProps extends StageStackProps {
  readonly table: dynamodb.Table;
  readonly staffUserPool: cognito.UserPool;
  readonly staffUserPoolClient: cognito.UserPoolClient;
}

/**
 * スライス①（menu-fn）＋②（cart-fn）＋③（order-fn/status-fn）＋④（store-fn）を配線したapp-stack。
 * WebSocket/SQS/EventBridge/ConnectionTable/payment-fnは対象外。
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

    // 受渡検知の合言葉(SSM SecureString)はCDKでは作らず、デプロイ後に手動で保存する運用のため
    // (計画の決定。共有アカウントと同じ理由)、実体を作らないfromSecureStringParameterAttributes()で
    // インポートし、IAM権限(grantRead、この1パラメータだけにスコープ)だけを付与する。
    const handoverApiKeyParameterName = `/mobile-order/${props.stage}/handover-api-key`;

    const storeFn = new PythonLambdaFunction(this, 'StoreFn', {
      functionName: `MobileOrder-${props.stage}-store-fn`,
      handler: 'handlers.store.handler',
      environment: {
        TABLE_NAME: props.table.tableName,
        HANDOVER_API_KEY_PARAMETER_NAME: handoverApiKeyParameterName,
      },
    });
    // store-fnはLINE状態更新・ZONESTAT加算(いずれもUpdateItem)を行う(TransactWriteItemsは使わない、
    // 計画の決定: 過去スライスで踏んだ落とし穴を避けるためLINE更新後の逐次UpdateItemに分割したため、
    // grantReadWriteData()だけで足り、order-fnのような個別のTransactWriteItems付与は不要)。
    props.table.grantReadWriteData(storeFn);

    const handoverApiKeyParameter = ssm.StringParameter.fromSecureStringParameterAttributes(
      this,
      'HandoverApiKeyParameter',
      { parameterName: handoverApiKeyParameterName },
    );
    handoverApiKeyParameter.grantRead(storeFn);

    const httpApi = new apigwv2.HttpApi(this, 'HttpApi', {
      apiName: `MobileOrder-${props.stage}-http-api`,
      // デフォルトステージをスロットル設定付きで自前定義するため、自動作成を無効化する。
      createDefaultStage: false,
      // web/は静的エクスポート(frontend-stack=S3+CloudFrontにNode.jsランタイムが無いため)を採用するため、
      // ブラウザのJavaScriptが直接このAPIを叩く。よってブラウザのSame-Origin PolicyによりCORS設定が
      // 必須になる(docs/architecture.md §1.3)。frontend-stack(スライス⑦)が実装されCloudFrontドメインが
      // 判明したら、allowOriginsにそのドメインを追加する。
      corsPreflight: {
        allowOrigins: ['http://localhost:3000'],
        allowMethods: [
          apigwv2.CorsHttpMethod.GET,
          apigwv2.CorsHttpMethod.POST,
          apigwv2.CorsHttpMethod.PUT,
          apigwv2.CorsHttpMethod.DELETE,
          apigwv2.CorsHttpMethod.PATCH,
        ],
        // Idempotency-Keyはorder-fnの冪等キー用カスタムヘッダ(§7.3)。Content-Typeはfetchのbody送信に必須。
        // AuthorizationはCognito JWT(store-fnの店員向け2ルート)をブラウザから送るために必要。
        allowHeaders: ['Content-Type', 'Idempotency-Key', 'Authorization'],
      },
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

    // 店員向け2ルート(一覧・状態更新)はCognitoでログイン済みかをAPI Gateway側で検証する
    // (docs/architecture.md §7.5)。受渡検知エンドポイントは自動受渡システム(機械)からの呼び出しで
    // Cognitoログインセッションを持たないため、このオーソライザーは付けない(ハンドラ内でx-api-keyを
    // 自分でチェックする、handlers/store.py参照)。
    const staffAuthorizer = new authorizers.HttpUserPoolAuthorizer(
      'StaffAuthorizer',
      props.staffUserPool,
      { userPoolClients: [props.staffUserPoolClient] },
    );

    const storeIntegration = new integrations.HttpLambdaIntegration('StoreIntegration', storeFn);
    const getZoneLinesRoutes = httpApi.addRoutes({
      path: '/stores/{storeId}/zones/{zone}/lines',
      methods: [apigwv2.HttpMethod.GET],
      integration: storeIntegration,
      authorizer: staffAuthorizer,
    });
    const updateLineStatusRoutes = httpApi.addRoutes({
      path: '/orders/{orderId}/lines/{lineId}/status',
      methods: [apigwv2.HttpMethod.PATCH],
      integration: storeIntegration,
      authorizer: staffAuthorizer,
    });
    const handoverLineRoutes = httpApi.addRoutes({
      path: '/orders/{orderId}/lines/{lineId}/handover',
      methods: [apigwv2.HttpMethod.PATCH],
      integration: storeIntegration,
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
      'GET /stores/{storeId}/zones/{zone}/lines': { ThrottlingRateLimit: 50, ThrottlingBurstLimit: 100 },
      'PATCH /orders/{orderId}/lines/{lineId}/status': { ThrottlingRateLimit: 20, ThrottlingBurstLimit: 40 },
      'PATCH /orders/{orderId}/lines/{lineId}/handover': { ThrottlingRateLimit: 20, ThrottlingBurstLimit: 40 },
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
      ...getZoneLinesRoutes,
      ...updateLineStatusRoutes,
      ...handoverLineRoutes,
    ]) {
      cfnDefaultStage.node.addDependency(route);
    }

    new cdk.CfnOutput(this, 'HttpApiUrl', {
      value: httpApi.apiEndpoint,
      exportName: `MobileOrder-${props.stage}-HttpApiUrl`,
    });
  }
}
