import type { UserRole } from "./auth";

export type UserStatus = "active" | "suspended";

export interface TenantUser {
  user_id: string;
  email: string;
  full_name: string;
  role: UserRole;
  tenant_id: string | null;
  status: UserStatus;
  created_at: string;
}

export interface CreateUserRequest {
  email: string;
  full_name: string;
  role: Extract<UserRole, "tenant_admin" | "agent">;
  tenant_id: string;
  // Optional — backend UserCreate.password (min 8 chars). User cannot log in until set.
  password?: string;
}

export interface UpdateUserRequest {
  full_name?: string;
  role?: Extract<UserRole, "tenant_admin" | "agent">;
  status?: UserStatus;
}
