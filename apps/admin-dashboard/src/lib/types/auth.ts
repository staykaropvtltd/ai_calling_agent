// Matches GET /api/auth/me response exactly.
// Update here when NK-05 changes the response shape.
export type UserRole = "super_admin" | "tenant_admin" | "agent";

export interface AuthUser {
  user_id: string;
  email: string;
  full_name: string;
  role: UserRole;
  tenant_id: string | null; // null for super_admin
  permissions: string[];
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number; // seconds
}

export interface LoginRequest {
  email: string;
  password: string;
}
