import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { fakeBackend, json } from "./test/backend";

vi.mock("./dashboard/FleetMap", () => ({ default: () => <div data-testid="fleet-map" /> }));

class MemoryStorage implements Storage {
  private m = new Map<string, string>();
  get length() {
    return this.m.size;
  }
  clear() {
    this.m.clear();
  }
  getItem(k: string) {
    return this.m.get(k) ?? null;
  }
  key(i: number) {
    return [...this.m.keys()][i] ?? null;
  }
  removeItem(k: string) {
    this.m.delete(k);
  }
  setItem(k: string, v: string) {
    this.m.set(k, v);
  }
}

const settle = async () => {
  for (let i = 0; i < 4; i++) await act(() => new Promise((r) => setTimeout(r, 0)));
};

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
});
afterEach(() => vi.useRealTimers());

async function signIn(role = "admin") {
  const b = fakeBackend((key) =>
    key === "GET /api/v1/me"
      ? json({ id: "U-1", role, name: "Transport Office", email: "admin1@campusride.demo" })
      : undefined,
  );
  const storage = new MemoryStorage();
  render(<App fetchImpl={b.fetchImpl} storage={storage} />);
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await settle();
  return { b, storage };
}

describe("Admin app — sign in → control room", () => {
  it("only admins can sign in (students and drivers are refused)", async () => {
    for (const role of ["student", "driver"]) {
      const { b } = await signIn(role);
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "This dashboard is for college transport admins only.",
      );
      expect(screen.queryByRole("region", { name: "Key figures" })).not.toBeInTheDocument();
      expect(b.count("GET /api/v1/admin/fleet")).toBe(0);
      document.body.innerHTML = "";
    }
  });

  it("an admin lands on the transport control room fed by /admin/*", async () => {
    const { b, storage } = await signIn();
    const kpis = await screen.findByRole("region", { name: "Key figures" });
    expect(within(kpis).getByRole("group", { name: "Total buses" })).toHaveTextContent("12");
    expect(screen.getByRole("table", { name: "Fleet table" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Sections" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Live status" })).toHaveTextContent("07:40:00");
    for (const k of ["overview", "fleet", "routes", "schedule", "analytics"]) {
      expect(b.count(`GET /api/v1/admin/${k}`)).toBe(1);
    }
    expect(storage.getItem("campusride.admin.session")).toContain("mock.t");
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(screen.getByRole("form", { name: "Admin sign in" })).toBeInTheDocument();
  });
});
