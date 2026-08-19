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

  test('UserPoolClientがUSER_PASSWORD_AUTHのみを有効にし、SRP/ADMIN_USER_PASSWORD_AUTHは無効（tasks/todo.md §31）', () => {
    const [client] = Object.values(template.findResources('AWS::Cognito::UserPoolClient'));
    const flows: string[] = client.Properties.ExplicitAuthFlows;
    expect(flows).toContain('ALLOW_USER_PASSWORD_AUTH');
    expect(flows).not.toContain('ALLOW_USER_SRP_AUTH');
    expect(flows).not.toContain('ALLOW_ADMIN_USER_PASSWORD_AUTH');
  });

  test('リフレッシュトークンの有効期限が共有タブレット紛失を想定して1日に短縮されている', () => {
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', {
      RefreshTokenValidity: 1440,
      TokenValidityUnits: Match.objectLike({ RefreshToken: 'minutes' }),
    });
  });
});
