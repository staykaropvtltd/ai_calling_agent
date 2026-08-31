import type { ReactElement } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import UsersPage from "../src/app/(dashboard)/users/page";
import * as usersApi from "../src/lib/api/users";
import * as useAuthModule from "../src/lib/auth/useAuth";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), back: vi.fn() }),
  useParams: () => ({}),
  usePathname: () => "/users",
}));
vi.mock("../src/lib/auth/useAuth");
vi.mock("../src/lib/api/users");

function renderWithQuery(ui: ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const tenantAdminAuth = {
  user: {
    user_id: "1",
    email: "ta@hotel.com",
    full_name: "Tenant Admin",
    role: "tenant_admin" as const,
    tenant_id: "1",
    permissions: [],
  },
  status: "authenticated" as const,
  login: vi.fn(),
  logout: vi.fn(),
};

const agentAuth = {
  user: {
    user_id: "2",
    email: "agent@hotel.com",
    full_name: "Front Desk Agent",
    role: "agent" as const,
    tenant_id: "1",
    permissions: [],
  },
  status: "authenticated" as const,
  login: vi.fn(),
  logout: vi.fn(),
};

const emptyPage = {
  data: [],
  total: 0,
  page: 1,
  per_page: 20,
  total_pages: 0,
};

describe("UsersPage — read-only, no user-management actions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(usersApi.listUsers).mockResolvedValue(emptyPage);
  });

  it("lists a tenant_admin's own-tenant users with no create/edit affordance", async () => {
    vi.mocked(useAuthModule.useAuth).mockReturnValue(tenantAdminAuth);
    renderWithQuery(<UsersPage />);
    await waitFor(() => expect(screen.queryByText("No users found.")).toBeInTheDocument());
    // This app never lets any role create/edit/suspend a user — that's
    // restricted to super_admin server-side (services/api/src/routers/
    // admin.py's _require_super_admin on create/update/delete).
    expect(screen.queryByText("New user")).not.toBeInTheDocument();
  });

  it("shows access-denied for agent (no /admin/users access server-side)", () => {
    vi.mocked(useAuthModule.useAuth).mockReturnValue(agentAuth);
    renderWithQuery(<UsersPage />);
    expect(screen.getByText(/access denied/i)).toBeInTheDocument();
  });
});
