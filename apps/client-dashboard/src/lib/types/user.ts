import type { UserRole } from "./auth";

export type UserStatus = "active" | "suspended";

// Matches GET /admin/users' UserResponse. Read-only in this app — only
// super_admin may create/update/delete users (services/api/src/routers/
// admin.py's _require_super_admin on those routes), so tenant_admin here
// only ever lists and views its own tenant's users.
export interface TenantUser {
  user_id: string;
  email: string;
  full_name: string;
  role: UserRole;
  tenant_id: string | null;
  status: UserStatus;
  created_at: string;
}
