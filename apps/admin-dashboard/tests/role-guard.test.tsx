import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { RoleGuard } from "../src/lib/auth/RoleGuard";
import * as useAuthModule from "../src/lib/auth/useAuth";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn(), back: vi.fn() }),
}));
vi.mock("../src/lib/auth/useAuth");

function mockAuth(overrides: Partial<ReturnType<typeof useAuthModule.useAuth>>) {
  vi.mocked(useAuthModule.useAuth).mockReturnValue({
    user: null,
    status: "loading",
    login: vi.fn(),
    logout: vi.fn(),
    ...overrides,
  });
}

describe("RoleGuard", () => {
  it("redirects to /login when unauthenticated", () => {
    mockAuth({ status: "unauthenticated", user: null });
    render(
      <RoleGuard allowedRoles={["super_admin"]}>
        <div>secret</div>
      </RoleGuard>,
    );
    expect(replace).toHaveBeenCalledWith("/login");
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("renders children for an allowed role (super_admin)", () => {
    mockAuth({
      status: "authenticated",
      user: {
        user_id: "1",
        email: "a@b.com",
        full_name: "A",
        role: "super_admin",
        tenant_id: null,
        permissions: [],
      },
    });
    render(
      <RoleGuard allowedRoles={["super_admin", "tenant_admin"]}>
        <div>secret</div>
      </RoleGuard>,
    );
    expect(screen.getByText("secret")).toBeInTheDocument();
  });

  it("shows access-denied for a role not in the allow-list (agent)", () => {
    mockAuth({
      status: "authenticated",
      user: {
        user_id: "2",
        email: "agent@b.com",
        full_name: "Agent",
        role: "agent",
        tenant_id: "1",
        permissions: [],
      },
    });
    render(
      <RoleGuard allowedRoles={["super_admin", "tenant_admin"]}>
        <div>secret</div>
      </RoleGuard>,
    );
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
    expect(screen.getByText(/access denied/i)).toBeInTheDocument();
  });
});
