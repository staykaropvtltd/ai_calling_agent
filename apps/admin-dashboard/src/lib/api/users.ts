import client from "./client";
import type { PaginatedResponse } from "../types/tenant";
import type { CreateUserRequest, TenantUser, UpdateUserRequest } from "../types/user";

export interface UserListParams {
  page?: number;
  per_page?: number;
  tenant_id?: string;
  role?: string;
  status?: string;
}

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

export async function createUser(payload: CreateUserRequest): Promise<TenantUser> {
  const { data } = await client.post<TenantUser>("/admin/users", payload);
  return data;
}

export async function updateUser(
  userId: string,
  payload: UpdateUserRequest,
): Promise<TenantUser> {
  const { data } = await client.put<TenantUser>(`/admin/users/${userId}`, payload);
  return data;
}

export async function deleteUser(userId: string): Promise<void> {
  await client.delete(`/admin/users/${userId}`);
}
