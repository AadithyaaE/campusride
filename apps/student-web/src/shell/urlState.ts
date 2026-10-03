import { useCallback, useEffect, useState } from "react";

/** View state lives in the URL so a refresh (or a shared link) restores it. */
export type Tab = "dashboard" | "mybus" | "stops" | "routes";
export const TABS: { id: Tab; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "mybus", label: "My Bus" },
  { id: "stops", label: "Stops" },
  { id: "routes", label: "Routes" },
];

export interface ViewState {
  tab: Tab;
  stop: string | null;
  route: string | null;
}

export function parseView(search: string): ViewState {
  const p = new URLSearchParams(search);
  const tab = p.get("tab");
  return {
    tab: TABS.some((t) => t.id === tab) ? (tab as Tab) : "dashboard",
    stop: p.get("stop") || null,
    route: p.get("route") || null,
  };
}

export function serializeView(v: ViewState, current: string): string {
  const p = new URLSearchParams(current);
  p.set("tab", v.tab);
  for (const key of ["stop", "route"] as const) {
    const value = v[key];
    if (value) p.set(key, value);
    else p.delete(key);
  }
  return `?${p.toString()}`;
}

export function useViewState(): [ViewState, (patch: Partial<ViewState>) => void] {
  const [view, setView] = useState<ViewState>(() => parseView(window.location.search));

  useEffect(() => {
    const onPop = () => setView(parseView(window.location.search));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const update = useCallback((patch: Partial<ViewState>) => {
    setView((prev) => {
      const next = { ...prev, ...patch };
      const url = serializeView(next, window.location.search) + window.location.hash;
      window.history.replaceState(null, "", url);
      return next;
    });
  }, []);

  return [view, update];
}
