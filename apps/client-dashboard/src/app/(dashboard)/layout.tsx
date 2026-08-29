"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { RoleGuard } from "../../lib/auth/RoleGuard";
import { useAuth } from "../../lib/auth/useAuth";
import type { UserRole } from "../../lib/types/auth";

interface NavItem {
  href: string;
  label: string;
  roles: UserRole[];
}

// "agent" only ever gets to place calls — /admin/users and /admin/calls
// require tenant_admin or super_admin (services/api/src/routers/admin.py's
// _require_admin), so those nav items would just 403 for an agent token.
const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Overview", roles: ["tenant_admin", "agent"] },
  { href: "/calls/new", label: "New call", roles: ["tenant_admin", "agent"] },
  { href: "/calls", label: "Calls", roles: ["tenant_admin"] },
  { href: "/users", label: "Users", roles: ["tenant_admin"] },
];

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <RoleGuard allowedRoles={["tenant_admin", "agent"]}>
      <DashboardShell>{children}</DashboardShell>
    </RoleGuard>
  );
}

function DashboardShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  if (!user) return null;

  const visibleItems = NAV_ITEMS.filter((item) => item.roles.includes(user.role));

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  return (
    <div className="flex min-h-screen bg-slate-50">
      <aside className="w-56 shrink-0 border-r border-slate-200 bg-white">
        <div className="px-4 py-5 text-base font-semibold text-slate-900">Staykaro</div>
        <nav className="flex flex-col gap-1 px-2">
          {visibleItems.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-md px-3 py-2 text-sm font-medium ${
                  active ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
          <div className="text-sm text-slate-500">
            {user.full_name} <span className="text-slate-300">·</span> {user.role}
          </div>
          <button
            type="button"
            onClick={handleLogout}
            className="text-sm font-medium text-slate-500 hover:text-slate-900"
          >
            Sign out
          </button>
        </header>
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
