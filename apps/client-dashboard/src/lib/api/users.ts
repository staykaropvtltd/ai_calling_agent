import client from "./client";
import type { PaginatedResponse } from "../types/common";
import type { TenantUser } from "../types/user";

export interface UserListParams {
  page?: number;
  per_page?: number;
  role?: string;
  status?: string;
}

// /client/users is tenant-scoped by the backend (_require_client_admin + RLS).
export async function listUsers(
  params: UserListParams = {},
): Promise<PaginatedResponse<TenantUser>> {
  const { data } = await client.get<PaginatedResponse<TenantUser>>("/client/users", { params });
  return data;
}

export async function getUser(userId: string): Promise<TenantUser> {
  const { data } = await client.get<TenantUser>(`/client/users/${userId}`);
  return data;
}
