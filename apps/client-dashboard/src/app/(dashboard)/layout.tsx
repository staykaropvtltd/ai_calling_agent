"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { RoleGuard } from "../../lib/auth/RoleGuard";
import { useAuth } from "../../lib/auth/useAuth";
import { useClientProfileQuery } from "../../lib/hooks/useSettings";
import type { UserRole } from "../../lib/types/auth";

interface NavGroup {
  label?: string;
  items: NavItem[];
}

interface NavItem {
  href: string;
  label: string;
  roles: UserRole[];
  exact?: boolean;
}

const NAV_GROUPS: NavGroup[] = [
  {
    items: [
      { href: "/", label: "Overview", roles: ["tenant_admin", "agent"], exact: true },
      { href: "/calls", label: "Calls", roles: ["tenant_admin", "agent"] },
      { href: "/calls/new", label: "New Call", roles: ["tenant_admin", "agent"] },
    ],
  },
  {
    label: "Analytics",
    items: [
      { href: "/analytics", label: "Analytics", roles: ["tenant_admin"] },
    ],
  },
  {
    label: "Management",
    items: [
      { href: "/ai-agent", label: "AI Agent", roles: ["tenant_admin"] },
      { href: "/phone-numbers", label: "Phone Numbers", roles: ["tenant_admin"] },
      { href: "/campaigns", label: "Campaigns", roles: ["tenant_admin"] },
      { href: "/business-hours", label: "Business Hours", roles: ["tenant_admin"] },
      { href: "/users", label: "Users & Roles", roles: ["tenant_admin"] },
      { href: "/integrations", label: "Integrations", roles: ["tenant_admin"] },
    ],
  },
  {
    label: "Account",
    items: [
      { href: "/usage", label: "Usage", roles: ["tenant_admin"] },
      { href: "/billing", label: "Billing & Plan", roles: ["tenant_admin"] },
      { href: "/settings", label: "Settings", roles: ["tenant_admin"] },
    ],
  },
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
  const { data: profile } = useClientProfileQuery();
  const pathname = usePathname();
  const router = useRouter();

  if (!user) return null;

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  function isActive(item: NavItem): boolean {
    if (item.exact) return pathname === item.href;
    return pathname === item.href || pathname.startsWith(item.href + "/");
  }

  return (
    <div className="flex min-h-screen bg-fog">
      {/* Sidebar */}
      <aside className="flex w-60 shrink-0 flex-col bg-graphite">
        {/* Logo */}
        <div className="flex items-center gap-3 px-6 py-5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-ember">
            <span className="font-display text-[10px] font-bold text-white">SK</span>
          </div>
          <div>
            <div className="font-display text-sm font-semibold tracking-display text-white">
              StayKaro
            </div>
            {profile?.tenant_name && (
              <div className="text-[10px] text-white/40 truncate max-w-[120px]">
                {profile.tenant_name}
              </div>
            )}
          </div>
        </div>

        <div className="h-px bg-white/8 mx-4" />

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto px-3 py-4">
          {NAV_GROUPS.map((group, gi) => {
            const visibleItems = group.items.filter((item) =>
              item.roles.includes(user.role),
            );
            if (visibleItems.length === 0) return null;
            return (
              <div key={gi} className={gi > 0 ? "mt-6" : ""}>
                {group.label && (
                  <div className="mb-1.5 px-3 text-[10px] font-medium uppercase tracking-widest text-white/30">
                    {group.label}
                  </div>
                )}
                <div className="flex flex-col gap-0.5">
                  {visibleItems.map((item) => {
                    const active = isActive(item);
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        className={[
                          "flex items-center gap-2.5 rounded-full px-3 py-2 text-sm font-medium transition-colors",
                          active
                            ? "bg-ember text-white font-display"
                            : "text-white/60 hover:bg-white/8 hover:text-white",
                        ].join(" ")}
                      >
                        {item.label}
                      </Link>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </nav>

        {/* User info + signout */}
        <div className="border-t border-white/8 px-4 py-4">
          <div className="mb-2 flex items-center gap-2.5">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white/10">
              <span className="font-display text-[10px] font-medium text-white">
                {user.full_name?.charAt(0) ?? "?"}
              </span>
            </div>
            <div className="min-w-0">
              <div className="truncate text-xs font-medium text-white">
                {user.full_name}
              </div>
              <div className="text-[10px] text-white/40">
                {user.role === "tenant_admin" ? "Admin" : "Agent"}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={handleLogout}
            className="w-full rounded-lg px-3 py-1.5 text-left text-xs text-white/40 transition-colors hover:bg-white/8 hover:text-white/70"
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex min-w-0 flex-1 flex-col">
        <main className="flex-1 overflow-auto p-8">{children}</main>
      </div>
    </div>
  );
}
