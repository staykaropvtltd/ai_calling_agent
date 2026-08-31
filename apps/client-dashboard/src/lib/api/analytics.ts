import client from "./client";
import type { AnalyticsData } from "../types/analytics";

export async function getAnalytics(): Promise<AnalyticsData> {
  const { data } = await client.get<AnalyticsData>("/client/analytics");
  return data;
}
