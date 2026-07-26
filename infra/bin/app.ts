#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { AppStack } from '../lib/app-stack';
import { Stage, StatefulStack } from '../lib/stateful-stack';

const VALID_STAGES: readonly Stage[] = ['dev', 'prod'];

function parseStage(value: unknown): Stage {
  if (typeof value !== 'string' || !(VALID_STAGES as readonly string[]).includes(value)) {
    throw new Error(
      `Invalid stage "${String(value)}". Must be one of: ${VALID_STAGES.join(', ')} `
        + '(via --context stage=<dev|prod> or STAGE env var).',
    );
  }
  return value as Stage;
}

const app = new cdk.App();

const stage = parseStage(app.node.tryGetContext('stage') ?? process.env.STAGE ?? 'dev');
const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION ?? 'ap-northeast-1',
};

const stateful = new StatefulStack(app, `MobileOrder-${stage}-Stateful`, { stage, env });
new AppStack(app, `MobileOrder-${stage}-App`, { stage, env, table: stateful.table });
