import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import axios, { AxiosError } from "axios";
import { ErrorBanner } from "../src/components/ErrorBanner";

function makeAxiosError(status: number, data: unknown): AxiosError {
  const err = new axios.AxiosError("Request failed");
  Object.defineProperty(err, "response", {
    value: { status, data },
    configurable: true,
  });
  return err;
}

describe("ErrorBanner", () => {
  it("shows a plain string detail from a 400 error", () => {
    const err = makeAxiosError(400, { detail: "Slug already exists" });
    render(<ErrorBanner error={err} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Slug already exists");
  });

  it("shows joined msg fields from a FastAPI 422 validation error array", () => {
    const err = makeAxiosError(422, {
      detail: [
        { type: "int_parsing", loc: ["body", "tenant_id"], msg: "Input should be a valid integer" },
        { type: "missing", loc: ["body", "email"], msg: "Field required" },
      ],
    });
    render(<ErrorBanner error={err} />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Input should be a valid integer; Field required",
    );
  });

  it("shows a session-expired message for 401 without a detail field", () => {
    const err = makeAxiosError(401, {});
    render(<ErrorBanner error={err} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Session expired");
  });

  it("shows 'Something went wrong' for an unknown error shape", () => {
    render(<ErrorBanner error={new Error("network down")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("network down");
  });

  it("shows fallback for a completely opaque error", () => {
    render(<ErrorBanner error="unexpected string thrown" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
  });
});
