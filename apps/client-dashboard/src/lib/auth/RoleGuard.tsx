"use client";

import { useEffect } from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "./useAuth";
import type { UserRole } from "../types/auth";
import { Spinner } from "../../components/Spinner";

interface RoleGuardProps {
  allowedRoles: UserRole[];
  children: ReactNode;
}

/**
 * Gate for the whole dashboard: redirects unauthenticated visitors to
 * /login, and shows a plain access-denied message for a role this app
 * doesn't serve (super_admin uses the separate admin-dashboard instead).
 * This is a UX guard only; the API is the real enforcement boundary —
 * see services/api/src/routers/admin.py's _require_admin/_require_super_admin.
 */
export function RoleGuard({ allowedRoles, children }: RoleGuardProps) {
  const { user, status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [status, router]);

  if (status === "loading") {
    return (
      <div className="flex h-screen items-center justify-center">
        <Spinner />
      </div>
    );
  }

  if (status === "unauthenticated" || !user) {
    return null;
  }

  if (!allowedRoles.includes(user.role)) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-2 text-center">
        <h1 className="text-xl font-semibold text-slate-900">Access denied</h1>
        <p className="text-sm text-slate-500">
          Your role ({user.role}) does not have access to this area.
        </p>
      </div>
    );
  }

  return <>{children}</>;
}
