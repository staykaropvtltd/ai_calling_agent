import client from "./client";
import type {
  CreateTenantRequest,
  PaginatedResponse,
  Tenant,
  TenantStats,
  UpdateTenantRequest,
} from "../types/tenant";

export interface TenantListParams {
  page?: number;
  per_page?: number;
  status?: string;
  search?: string;
}

export async function listTenants(
  params: TenantListParams = {},
): Promise<PaginatedResponse<Tenant>> {
  const { data } = await client.get<PaginatedResponse<Tenant>>("/admin/tenants", { params });
  return data;
}

export async function getTenant(tenantId: string): Promise<Tenant> {
  const { data } = await client.get<Tenant>(`/admin/tenants/${tenantId}`);
  return data;
}

export async function createTenant(payload: CreateTenantRequest): Promise<Tenant> {
  const { data } = await client.post<Tenant>("/admin/tenants", payload);
  return data;
}

export async function updateTenant(
  tenantId: string,
  payload: UpdateTenantRequest,
): Promise<Tenant> {
  const { data } = await client.put<Tenant>(`/admin/tenants/${tenantId}`, payload);
  return data;
}

export async function deleteTenant(tenantId: string): Promise<void> {
  await client.delete(`/admin/tenants/${tenantId}`);
}

export async function getTenantStats(tenantId: string): Promise<TenantStats> {
  const { data } = await client.get<TenantStats>(`/admin/tenants/${tenantId}/stats`);
  return data;
}
