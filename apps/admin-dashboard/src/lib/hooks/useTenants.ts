import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createTenant,
  deleteTenant,
  getTenant,
  getTenantStats,
  listTenants,
  updateTenant,
  type TenantListParams,
} from "../api/tenants";
import type { CreateTenantRequest, UpdateTenantRequest } from "../types/tenant";

const KEY = "tenants";

export function useTenantsQuery(params: TenantListParams) {
  return useQuery({
    queryKey: [KEY, params],
    queryFn: () => listTenants(params),
  });
}

export function useTenantQuery(tenantId: string | undefined) {
  return useQuery({
    queryKey: [KEY, tenantId],
    queryFn: () => getTenant(tenantId as string),
    enabled: Boolean(tenantId),
  });
}

export function useTenantStatsQuery(tenantId: string | undefined) {
  return useQuery({
    queryKey: [KEY, tenantId, "stats"],
    queryFn: () => getTenantStats(tenantId as string),
    enabled: Boolean(tenantId),
  });
}

export function useCreateTenant() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateTenantRequest) => createTenant(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}

export function useUpdateTenant(tenantId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: UpdateTenantRequest) => updateTenant(tenantId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}

export function useDeleteTenant() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (tenantId: string) => deleteTenant(tenantId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}
