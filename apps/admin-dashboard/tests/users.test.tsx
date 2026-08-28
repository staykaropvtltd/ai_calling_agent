import type { ReactElement } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import UsersPage from "../src/app/(dashboard)/users/page";
import NewUserPage from "../src/app/(dashboard)/users/new/page";
import * as usersApi from "../src/lib/api/users";
import * as tenantsApi from "../src/lib/api/tenants";
import * as useAuthModule from "../src/lib/auth/useAuth";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), back: vi.fn() }),
  useParams: () => ({}),
  usePathname: () => "/users",
}));
vi.mock("../src/lib/auth/useAuth");
vi.mock("../src/lib/api/users");
vi.mock("../src/lib/api/tenants");

function renderWithQuery(ui: ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const superAdminAuth = {
  user: {
    user_id: "1",
    email: "admin@staykaro.com",
    full_name: "Admin",
    role: "super_admin" as const,
    tenant_id: null,
    permissions: [],
  },
  status: "authenticated" as const,
  login: vi.fn(),
  logout: vi.fn(),
};

const tenantAdminAuth = {
  user: {
    user_id: "2",
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

const emptyPage = {
  data: [],
  total: 0,
  page: 1,
  per_page: 20,
  total_pages: 0,
};

describe("UsersPage — New user button visibility", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(usersApi.listUsers).mockResolvedValue(emptyPage);
  });

  it("shows New user button for super_admin", async () => {
    vi.mocked(useAuthModule.useAuth).mockReturnValue(superAdminAuth);
    renderWithQuery(<UsersPage />);
    await waitFor(() => expect(screen.queryByText("No users yet.")).toBeInTheDocument());
    expect(screen.getByText("New user")).toBeInTheDocument();
  });

  it("hides New user button for tenant_admin", async () => {
    vi.mocked(useAuthModule.useAuth).mockReturnValue(tenantAdminAuth);
    renderWithQuery(<UsersPage />);
    await waitFor(() => expect(screen.queryByText("No users yet.")).toBeInTheDocument());
    expect(screen.queryByText("New user")).not.toBeInTheDocument();
  });
});

describe("NewUserPage — tenant select", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useAuthModule.useAuth).mockReturnValue(superAdminAuth);
    vi.mocked(usersApi.createUser).mockResolvedValue({
      user_id: "new-uuid",
      email: "x@y.com",
      full_name: "X",
      role: "agent",
      tenant_id: "1",
      status: "active",
      created_at: "2026-01-01T00:00:00Z",
    });
  });

  it("renders a tenant <select> populated from the tenants API", async () => {
    vi.mocked(tenantsApi.listTenants).mockResolvedValue({
      data: [
        {
          tenant_id: "1",
          name: "Acme Hotels",
          slug: "acme-hotels",
          plan: "pro",
          status: "active",
          contact_email: "ops@acme.com",
          max_concurrent_calls: 10,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
        {
          tenant_id: "2",
          name: "Best Stay",
          slug: "best-stay",
          plan: "starter",
          status: "active",
          contact_email: "ops@best.com",
          max_concurrent_calls: 5,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
      total: 2,
      page: 1,
      per_page: 100,
      total_pages: 1,
    });

    renderWithQuery(<NewUserPage />);

    // The tenant select should eventually list both tenants
    await waitFor(() =>
      expect(screen.getByRole("option", { name: /Acme Hotels/ })).toBeInTheDocument(),
    );
    expect(screen.getByRole("option", { name: /Best Stay/ })).toBeInTheDocument();
  });

  it("shows a placeholder option while tenants load", () => {
    // listTenants never resolves in this test — checks the loading state
    vi.mocked(tenantsApi.listTenants).mockReturnValue(new Promise(() => {}));

    renderWithQuery(<NewUserPage />);

    expect(screen.getByRole("option", { name: /Loading tenants/i })).toBeInTheDocument();
  });
});
