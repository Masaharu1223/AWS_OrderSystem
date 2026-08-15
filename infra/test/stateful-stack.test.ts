import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { StatefulStack } from '../lib/stateful-stack';

describe('StatefulStack', () => {
  const app = new cdk.App();
  const stack = new StatefulStack(app, 'TestStateful', {
    stage: 'dev',
    env: { account: '123456789012', region: 'ap-northeast-1' },
  });
  const template = Template.fromStack(stack);

  test('MobileOrderTableがPK/SK・課金モード・ストリーム・PITRを正しく設定している（物理名は固定しない）', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: Match.absent(),
      KeySchema: [
        { AttributeName: 'PK', KeyType: 'HASH' },
        { AttributeName: 'SK', KeyType: 'RANGE' },
      ],
      BillingMode: 'PAY_PER_REQUEST',
      StreamSpecification: { StreamViewType: 'NEW_AND_OLD_IMAGES' },
      PointInTimeRecoverySpecification: { PointInTimeRecoveryEnabled: true },
    });
  });

  test('TTL属性がexpiresAtで有効化されている（テーブル全体で単一のTTL属性を共有）', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TimeToLiveSpecification: { AttributeName: 'expiresAt', Enabled: true },
    });
  });

  test('スタック自体のCFN終了保護が有効', () => {
    expect(stack.terminationProtection).toBe(true);
  });

  test('GSI1・GSI2が正しいキースキーマで定義されている（GSI2SKはNumber型）', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      AttributeDefinitions: Match.arrayWith([
        { AttributeName: 'GSI1PK', AttributeType: 'S' },
        { AttributeName: 'GSI1SK', AttributeType: 'S' },
        { AttributeName: 'GSI2PK', AttributeType: 'S' },
        { AttributeName: 'GSI2SK', AttributeType: 'N' },
      ]),
      GlobalSecondaryIndexes: Match.arrayWith([
        Match.objectLike({
          IndexName: 'GSI1',
          KeySchema: [
            { AttributeName: 'GSI1PK', KeyType: 'HASH' },
            { AttributeName: 'GSI1SK', KeyType: 'RANGE' },
          ],
        }),
        Match.objectLike({
          IndexName: 'GSI2',
          KeySchema: [
            { AttributeName: 'GSI2PK', KeyType: 'HASH' },
            { AttributeName: 'GSI2SK', KeyType: 'RANGE' },
          ],
        }),
      ]),
    });
  });

  test('RemovalPolicy.RETAINと終了保護が有効（誤削除防止）', () => {
    template.hasResource('AWS::DynamoDB::Table', {
      DeletionPolicy: 'Retain',
      UpdateReplacePolicy: 'Retain',
      Properties: Match.objectLike({ DeletionProtectionEnabled: true }),
    });
  });

  test('店員向けUserPoolがセルフサインアップ無効・RETAIN・終了保護で1個だけ作られる（共有アカウントはデプロイ後に手動作成）', () => {
    template.resourceCountIs('AWS::Cognito::UserPool', 1);
    template.hasResourceProperties('AWS::Cognito::UserPool', {
      UserPoolName: 'MobileOrder-dev-staff-user-pool',
      AdminCreateUserConfig: Match.objectLike({ AllowAdminCreateUserOnly: true }),
      DeletionProtection: 'ACTIVE',
    });
    template.hasResource('AWS::Cognito::UserPool', {
      DeletionPolicy: 'Retain',
      UpdateReplacePolicy: 'Retain',
    });
  });

  test('UserPoolClientがSRPとADMIN_USER_PASSWORD_AUTHの両方を有効にしている（curl/aws-cli動作確認用）', () => {
    // arrayWith()は相対順序を維持したサブシーケンス一致のため、1要素ずつ個別に検証する
    // (CDKが生成するExplicitAuthFlowsの実際の並び順に依存しないようにするため)。
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', {
      ExplicitAuthFlows: Match.arrayWith(['ALLOW_USER_SRP_AUTH']),
    });
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', {
      ExplicitAuthFlows: Match.arrayWith(['ALLOW_ADMIN_USER_PASSWORD_AUTH']),
    });
  });
});
