import { ZoneQueueScreen } from "@/components/staff/ZoneQueueScreen";
import type { Zone } from "@/lib/staff";

// 要件定義書§5.1: A/B/C/Dのフラットな一覧。generateStaticParamsはNode.js(ビルド時)専用の
// 特殊exportのため、"use client"を持つファイルには置けない。このpage.tsx自体は薄いServer
// Componentのままにし、実際のインタラクティブな描画はClient ComponentのZoneQueueScreenへ委譲する。
const ZONES: readonly Zone[] = ["A", "B", "C", "D"];

export function generateStaticParams() {
  return ZONES.map((zone) => ({ zone }));
}

export default async function ZonePage({
  params,
}: {
  params: Promise<{ zone: string }>;
}) {
  const { zone } = await params;
  return <ZoneQueueScreen zone={zone as Zone} />;
}
