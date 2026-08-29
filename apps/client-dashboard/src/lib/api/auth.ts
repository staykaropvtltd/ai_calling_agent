import client, { clearTokens, setTokens } from "./client";
import type { AuthUser, LoginRequest, MeResponseRaw, TokenResponse } from "../types/auth";

export async function login(payload: LoginRequest): Promise<AuthUser> {
  const { data } = await client.post<TokenResponse>("/auth/login", payload);
  setTokens(data.access_token, data.refresh_token);
  return getMe();
}

export async function logout(): Promise<void> {
  try {
    await client.post("/auth/logout");
  } finally {
    clearTokens();
  }
}

export async function getMe(): Promise<AuthUser> {
  const { data } = await client.get<MeResponseRaw>("/auth/me");
  return {
    ...data,
    tenant_id: data.tenant_id != null ? String(data.tenant_id) : null,
  };
}
