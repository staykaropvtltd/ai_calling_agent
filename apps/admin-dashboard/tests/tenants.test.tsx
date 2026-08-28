import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import TenantsPage from "../src/app/(dashboard)/tenants/page";
import * as tenantsApi from "../src/lib/api/tenants";
import * as useAuthModule from "../src/lib/auth/useAuth";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), back: vi.fn() }),
}));
vi.mock("../src/lib/auth/useAuth");
vi.mock("../src/lib/api/tenants");

function renderWithQuery(ui: ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("TenantsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders a list of tenants for a super_admin", async () => {
    vi.mocked(useAuthModule.useAuth).mockReturnValue({
      user: {
        user_id: "1",
        email: "admin@staykaro.com",
        full_name: "Admin",
        role: "super_admin",
        tenant_id: null,
        permissions: [],
      },
      status: "authenticated",
      login: vi.fn(),
      logout: vi.fn(),
    });

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
      ],
      total: 1,
      page: 1,
      per_page: 20,
      total_pages: 1,
    });

    renderWithQuery(<TenantsPage />);

    await waitFor(() => expect(screen.getByText("Acme Hotels")).toBeInTheDocument());
    expect(screen.getByText("acme-hotels")).toBeInTheDocument();
    expect(screen.getByText("New tenant")).toBeInTheDocument();
  });

  it("shows access-denied for a tenant_admin", () => {
    vi.mocked(useAuthModule.useAuth).mockReturnValue({
      user: {
        user_id: "2",
        email: "ta@acme.com",
        full_name: "Tenant Admin",
        role: "tenant_admin",
        tenant_id: "1",
        permissions: [],
      },
      status: "authenticated",
      login: vi.fn(),
      logout: vi.fn(),
    });

    renderWithQuery(<TenantsPage />);

    expect(screen.getByText(/access denied/i)).toBeInTheDocument();
    expect(tenantsApi.listTenants).not.toHaveBeenCalled();
  });
});
