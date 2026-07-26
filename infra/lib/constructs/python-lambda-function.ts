import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';

// AWS公式Powertools Lambda Layer（Python 3.12 / arm64）のARNをSSMパラメータから動的解決する。
// バージョンをハードコードせず、deploy時にCFN動的参照として解決されるため常に最新に追随する。
const POWERTOOLS_LAYER_SSM_PARAM = '/aws/service/powertools/python/arm64/python3.12/latest';

// services/src を指す。infra/lib/constructs/ からの相対パス。
const SERVICES_SRC_PATH = path.join(__dirname, '..', '..', '..', 'services', 'src');

export interface PythonLambdaFunctionProps {
  readonly functionName: string;
  /** 例: "handlers.menu.handler" */
  readonly handler: string;
  readonly environment?: Record<string, string>;
  readonly timeout?: cdk.Duration;
  readonly memorySize?: number;
}

/**
 * services/src をZip化してPython 3.12 (arm64) LambdaにPowertools Layerを付けてデプロイする共通コンストラクト。
 * aws-lambda-python-alpha (PythonFunction) は使わず、安定版 lambda.Function + Code.fromAsset を使う。
 */
export class PythonLambdaFunction extends lambda.Function {
  constructor(scope: Construct, id: string, props: PythonLambdaFunctionProps) {
    const powertoolsLayerArn = ssm.StringParameter.valueForStringParameter(
      scope,
      POWERTOOLS_LAYER_SSM_PARAM,
    );

    super(scope, id, {
      functionName: props.functionName,
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.ARM_64,
      handler: props.handler,
      code: lambda.Code.fromAsset(SERVICES_SRC_PATH, {
        exclude: ['**/__pycache__/**', '**/*.pyc', '**/.pytest_cache/**', '**/.mypy_cache/**'],
      }),
      layers: [
        lambda.LayerVersion.fromLayerVersionArn(scope, `${id}PowertoolsLayer`, powertoolsLayerArn),
      ],
      environment: {
        POWERTOOLS_SERVICE_NAME: props.functionName,
        LOG_LEVEL: 'INFO',
        ...props.environment,
      },
      timeout: props.timeout ?? cdk.Duration.seconds(10),
      memorySize: props.memorySize ?? 256,
      tracing: lambda.Tracing.ACTIVE,
    });
  }
}
