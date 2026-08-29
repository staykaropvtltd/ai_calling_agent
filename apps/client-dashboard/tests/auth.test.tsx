import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AuthProvider } from "../src/lib/auth/AuthProvider";
import { useAuth } from "../src/lib/auth/useAuth";
import * as authApi from "../src/lib/api/auth";
import { clearTokens } from "../src/lib/api/client";

vi.mock("../src/lib/api/auth");

const mockUser = {
  user_id: "u1",
  email: "frontdesk@hotel.com",
  full_name: "Front Desk",
  role: "tenant_admin" as const,
  tenant_id: "1",
  permissions: ["user:read", "call:read"],
};

function Harness() {
  const { user, status, login } = useAuth();
  return (
    <div>
      <div data-testid="status">{status}</div>
      <div data-testid="email">{user?.email ?? "none"}</div>
      <button
        onClick={() =>
          login({ email: "frontdesk@hotel.com", password: "secret123" }).catch(() => undefined)
        }
      >
        login
      </button>
    </div>
  );
}

describe("AuthProvider", () => {
  beforeEach(() => {
    clearTokens();
    vi.clearAllMocks();
  });

  it("starts unauthenticated with no stored token", async () => {
    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
  });

  it("becomes authenticated after a successful login", async () => {
    vi.mocked(authApi.login).mockResolvedValue(mockUser);

    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));

    await userEvent.click(screen.getByText("login"));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("email")).toHaveTextContent("frontdesk@hotel.com");
  });

  it("stays unauthenticated when login rejects", async () => {
    vi.mocked(authApi.login).mockRejectedValue(new Error("Invalid credentials"));

    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));

    await userEvent.click(screen.getByText("login"));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(screen.getByTestId("email")).toHaveTextContent("none");
  });
});
