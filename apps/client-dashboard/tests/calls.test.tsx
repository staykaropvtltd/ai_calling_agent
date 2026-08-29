import type { ReactElement } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import NewCallPage from "../src/app/(dashboard)/calls/new/page";
import CallsPage from "../src/app/(dashboard)/calls/page";
import * as callsApi from "../src/lib/api/calls";
import * as useAuthModule from "../src/lib/auth/useAuth";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), back: vi.fn() }),
  useParams: () => ({}),
  usePathname: () => "/calls/new",
}));
vi.mock("../src/lib/auth/useAuth");
vi.mock("../src/lib/api/calls");

function renderWithQuery(ui: ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

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

describe("NewCallPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(callsApi.createCall).mockResolvedValue({
      status: "success",
      database: "Saved",
      redis_session: "abc-123",
    });
  });

  it("lets an agent (no /admin/calls access) place a call and shows no 'View calls' link", async () => {
    vi.mocked(useAuthModule.useAuth).mockReturnValue(agentAuth);
    renderWithQuery(<NewCallPage />);

    await userEvent.type(screen.getByLabelText(/Customer name/), "Raj Kumar");
    await userEvent.type(screen.getByLabelText(/Phone number/), "+919876543210");
    await userEvent.type(screen.getByLabelText(/Hotel name/), "Taj Palace");
    await userEvent.type(screen.getByLabelText(/Check-in date/), "2026-09-01");
    await userEvent.type(screen.getByLabelText(/Check-out date/), "2026-09-03");
    await userEvent.click(screen.getByRole("button", { name: /Place call/ }));

    await waitFor(() =>
      expect(callsApi.createCall).toHaveBeenCalledWith({
        customer_name: "Raj Kumar",
        phone_number: "+919876543210",
        hotel_name: "Taj Palace",
        check_in_date: "2026-09-01",
        check_out_date: "2026-09-03",
      }),
    );
    expect(await screen.findByText(/has been queued/)).toBeInTheDocument();
    expect(screen.queryByText("View calls")).not.toBeInTheDocument();
  });

  it("shows a 'View calls' link for tenant_admin after placing a call", async () => {
    vi.mocked(useAuthModule.useAuth).mockReturnValue(tenantAdminAuth);
    renderWithQuery(<NewCallPage />);

    await userEvent.type(screen.getByLabelText(/Customer name/), "Priya Singh");
    await userEvent.type(screen.getByLabelText(/Phone number/), "+919876500000");
    await userEvent.type(screen.getByLabelText(/Hotel name/), "Best Stay");
    await userEvent.type(screen.getByLabelText(/Check-in date/), "2026-09-05");
    await userEvent.type(screen.getByLabelText(/Check-out date/), "2026-09-06");
    await userEvent.click(screen.getByRole("button", { name: /Place call/ }));

    expect(await screen.findByText("View calls")).toBeInTheDocument();
  });
});

describe("CallsPage — role gating", () => {
  it("shows access-denied for agent (no /admin/calls access server-side)", () => {
    vi.mocked(useAuthModule.useAuth).mockReturnValue(agentAuth);
    renderWithQuery(<CallsPage />);
    expect(screen.getByText(/access denied/i)).toBeInTheDocument();
  });
});
