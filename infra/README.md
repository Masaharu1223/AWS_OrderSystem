# Welcome to your CDK TypeScript project

This is a blank project for CDK development with TypeScript.

The `cdk.json` file tells the CDK Toolkit how to execute your app.

## Useful commands

このディレクトリの依存は **bun** で管理する（ロックファイルは `bun.lock`。CI も bun を使う）。

* `bun install`        install dependencies
* `bun run build`      type-check the project
* `bun run watch`      watch for changes and type-check
* `bun run test`       perform the jest unit tests
* `bunx cdk deploy`    deploy this stack to your default AWS account/region
* `bunx cdk diff`      compare deployed stack with current state
* `bunx cdk synth`     emits the synthesized CloudFormation template
