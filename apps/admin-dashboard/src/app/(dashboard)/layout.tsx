"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { RoleGuard } from "../../lib/auth/RoleGuard";
import { useAuth } from "../../lib/auth/useAuth";

interface NavItem {
  href: string;
  label: string;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: "",
    items: [
      { href: "/", label: "Overview" },
      { href: "/tenants", label: "Clients" },
      { href: "/users", label: "Users" },
      { href: "/calls", label: "Calls" },
    ],
  },
  {
    label: "Analytics",
    items: [
      { href: "/analytics", label: "Platform Analytics" },
      { href: "/usage", label: "Usage" },
    ],
  },
  {
    label: "Platform",
    items: [
      { href: "/phone-numbers", label: "Phone Numbers" },
      { href: "/ai-voice", label: "AI / Voice" },
      { href: "/integrations", label: "Integrations" },
    ],
  },
  {
    label: "Operations",
    items: [
      { href: "/jobs", label: "Jobs & Workers" },
      { href: "/system-health", label: "System Health" },
      { href: "/audit-logs", label: "Audit Logs" },
    ],
  },
  {
    label: "Settings",
    items: [{ href: "/settings", label: "Platform Settings" }],
  },
];

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <RoleGuard allowedRoles={["super_admin", "tenant_admin"]}>
      <DashboardShell>{children}</DashboardShell>
    </RoleGuard>
  );
}

function DashboardShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  if (!user) return null;

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  function isActive(href: string) {
    return href === "/" ? pathname === "/" : pathname.startsWith(href);
  }

  return (
    <div className="flex min-h-screen">
      {/* Dark graphite sidebar */}
      <aside className="flex w-60 shrink-0 flex-col bg-graphite">
        {/* Logo */}
        <div className="flex items-center gap-3 px-5 py-6">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ember">
            <span className="font-display text-xs font-bold text-white">SK</span>
          </div>
          <span className="font-display text-sm font-semibold text-white">StayKaro Admin</span>
        </div>

        {/* Nav */}
        <nav className="flex flex-1 flex-col gap-6 overflow-y-auto px-3 pb-6">
          {NAV_GROUPS.map((group) => (
            <div key={group.label || "main"}>
              {group.label && (
                <p className="mb-1 px-3 text-[10px] font-medium uppercase tracking-widest text-white/30">
                  {group.label}
                </p>
              )}
              <div className="flex flex-col gap-0.5">
                {group.items.map((item) => {
                  const active = isActive(item.href);
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={[
                        "rounded-full px-3 py-2 font-display text-sm font-medium transition-colors",
                        active
                          ? "bg-ember text-white"
                          : "text-white/60 hover:bg-white/8 hover:text-white",
                      ].join(" ")}
                    >
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* User info */}
        <div className="border-t border-white/10 px-4 py-4">
          <p className="text-xs font-medium text-white/80">{user.full_name || user.email}</p>
          <p className="mt-0.5 text-[10px] text-white/40">{user.role}</p>
          <button
            type="button"
            onClick={handleLogout}
            className="mt-3 font-display text-xs text-white/40 hover:text-white/80"
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* Main area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <main className="flex-1 overflow-auto p-8">{children}</main>
      </div>
    </div>
  );
}
