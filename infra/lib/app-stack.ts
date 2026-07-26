import * as cdk from 'aws-cdk-lib';
import * as apigwv2 from 'aws-cdk-lib/aws-apigatewayv2';
import * as integrations from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';
import { PythonLambdaFunction } from './constructs/python-lambda-function';
import { StageStackProps } from './stateful-stack';

export interface AppStackProps extends StageStackProps {
  readonly table: dynamodb.Table;
}

/**
 * スライス①（menu-fn）のみを配線した最小版app-stack。
 * cart/order/status/store/WebSocket/SQS/EventBridge/Cognito/ConnectionTable/payment-fnは対象外。
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

    const httpApi = new apigwv2.HttpApi(this, 'HttpApi', {
      apiName: `MobileOrder-${props.stage}-http-api`,
      // デフォルトステージをスロットル設定付きで自前定義するため、自動作成を無効化する。
      createDefaultStage: false,
    });

    // 公開エンドポイント（認証なし）にバースト/レート上限を設定し、過負荷・濫用を防ぐ。
    new apigwv2.HttpStage(this, 'DefaultStage', {
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

    new cdk.CfnOutput(this, 'HttpApiUrl', {
      value: httpApi.apiEndpoint,
      exportName: `MobileOrder-${props.stage}-HttpApiUrl`,
    });
  }
}
