/** Read-only route view: the backend's ordered stops with progress from tracking. */
import { useCallback, useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import type { DriverApi, DriverRouteView } from "../api/client";
import { Banner, BigButton, colors } from "../components/ui";
import { friendlyError } from "../utils/messages";

const MARK = { passed: "✓", current: "●", next: "➜", upcoming: "○" } as const;
const LABEL = {
  passed: "passed",
  current: "at / last stop",
  next: "next stop",
  upcoming: "",
} as const;

export function RouteScreen({ api, onBack }: { api: DriverApi; onBack: () => void }) {
  const [view, setView] = useState<DriverRouteView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api.route().then(
      (v) => (setView(v), setError(null)),
      (e: unknown) => setError(friendlyError(e, "Route could not be loaded.")),
    );
  }, [api]);
  useEffect(load, [load]);

  return (
    <ScrollView contentContainerStyle={s.page}>
      <Text style={s.title}>ROUTE</Text>
      {error && <Banner text={error} tone="error" />}
      {view?.route && (
        <Text style={s.route}>
          {view.route.name}
          {view.route.label ? ` · ${view.route.label}` : ""}
        </Text>
      )}
      {view && view.stops.length === 0 && <Text style={s.muted}>No route for today.</Text>}
      {view?.stops.map((st) => (
        <View
          key={st.seq}
          style={[s.stop, st.state === "next" && s.next]}
          accessible
          accessibilityLabel={`Stop ${st.seq + 1}: ${st.name}, ${st.state}`}
        >
          <Text style={[s.mark, st.state === "passed" && s.passed]}>{MARK[st.state]}</Text>
          <Text style={[s.name, st.state === "passed" && s.passed]}>{st.name}</Text>
          <Text style={s.tag}>{LABEL[st.state]}</Text>
        </View>
      ))}
      {view?.bus_location && (
        <Text style={s.muted}>
          Bus at {view.bus_location.lat.toFixed(5)}, {view.bus_location.lon.toFixed(5)} (simulated)
        </Text>
      )}
      <BigButton label="REFRESH" variant="secondary" onPress={load} />
      <BigButton label="BACK" onPress={onBack} />
    </ScrollView>
  );
}

const s = StyleSheet.create({
  page: { padding: 20, paddingTop: 48, backgroundColor: colors.bg, flexGrow: 1 },
  title: { fontSize: 14, fontWeight: "800", color: colors.muted, letterSpacing: 1 },
  route: { fontSize: 22, fontWeight: "900", color: colors.ink, marginBottom: 12 },
  stop: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.line,
  },
  next: { backgroundColor: "#ecfdf5" },
  mark: { width: 24, fontSize: 18, fontWeight: "900", color: colors.brand, textAlign: "center" },
  name: { flex: 1, fontSize: 18, fontWeight: "700", color: colors.ink },
  passed: { color: colors.muted },
  tag: { fontSize: 13, color: colors.muted },
  muted: { marginTop: 10, color: colors.muted },
});
