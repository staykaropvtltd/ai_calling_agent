import client from "./client";
import type { PaginatedResponse } from "../types/common";
import type { TenantUser } from "../types/user";

export interface UserListParams {
  page?: number;
  per_page?: number;
  role?: string;
  status?: string;
}

// /admin/users is tenant-scoped server-side for tenant_admin tokens — see
// listCalls' comment in ./calls.ts, same mechanism.
export async function listUsers(
  params: UserListParams = {},
): Promise<PaginatedResponse<TenantUser>> {
  const { data } = await client.get<PaginatedResponse<TenantUser>>("/admin/users", { params });
  return data;
}

export async function getUser(userId: string): Promise<TenantUser> {
  const { data } = await client.get<TenantUser>(`/admin/users/${userId}`);
  return data;
}
