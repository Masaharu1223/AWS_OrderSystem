import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // frontend-stack(S3+CloudFront/OAC)はNode.jsランタイムを持たないため静的エクスポートを採用する
  // (docs/architecture.md §1.3)。trailingSlashはCloudFront配信時のindex.html解決(スライス⑦)を見据えた前提合わせ。
  output: "export",
  trailingSlash: true,
};

export default nextConfig;
