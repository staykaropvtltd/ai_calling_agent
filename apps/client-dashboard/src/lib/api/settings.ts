import client from "./client";
import type { ClientProfile } from "../types/tenant";

// GET /client/me — returns the authenticated user's profile combined with
// their tenant's configuration (including internationalisation fields).
// Accessible to both tenant_admin and agent.
export async function getClientProfile(): Promise<ClientProfile> {
  const { data } = await client.get<ClientProfile>("/client/me");
  return data;
}
