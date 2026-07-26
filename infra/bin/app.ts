#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { AppStack } from '../lib/app-stack';
import { Stage, StatefulStack } from '../lib/stateful-stack';

const app = new cdk.App();

const stage = (app.node.tryGetContext('stage') ?? process.env.STAGE ?? 'dev') as Stage;
const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION ?? 'ap-northeast-1',
};

const stateful = new StatefulStack(app, `MobileOrder-${stage}-Stateful`, { stage, env });
new AppStack(app, `MobileOrder-${stage}-App`, { stage, env, table: stateful.table });
