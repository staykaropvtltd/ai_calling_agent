export type TenantPlan = "starter" | "pro" | "enterprise";
export type TenantStatus = "active" | "suspended" | "inactive";

export interface Tenant {
  tenant_id: string;
  name: string;
  slug: string;
  plan: TenantPlan;
  status: TenantStatus;
  // nullable=True in DB (clients.contact_email); Optional[str] in TenantResponse.
  contact_email: string | null;
  // server_default=10 in DB but no nullable=False; Optional[int] in TenantResponse.
  max_concurrent_calls: number | null;
  created_at: string; // ISO8601; server_default=now() — always set in practice
  updated_at: string;
}

export interface TenantStats {
  tenant_id: string;
  total_calls: number;
  calls_this_month: number;
  active_users: number;
  plan_call_limit: number;
  plan_usage_pct: number;
}

export interface CreateTenantRequest {
  name: string;
  slug: string;
  plan: TenantPlan;
  contact_email: string;
  max_concurrent_calls: number;
}

export interface UpdateTenantRequest {
  name?: string;
  plan?: TenantPlan;
  status?: TenantStatus;
  contact_email?: string;
  max_concurrent_calls?: number;
}

export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}
