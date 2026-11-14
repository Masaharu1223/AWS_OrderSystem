import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 配信はAmplify Hostingの静的配信(platform: WEB、infra/lib/constructs/web-hosting.ts)で、
  // Node.jsランタイムを持たないため静的エクスポートを採用する。trailingSlashで各ページを
  // `<path>/index.html`として出力し、Amplifyが`/cart/`→`cart/index.html`と解決できるようにする
  // (`/cart`は`/cart/`へ301転送される)。
  output: "export",
  trailingSlash: true,
};

export default nextConfig;
