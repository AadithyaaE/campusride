/**
 * CampusRide Driver (Feature 12) — a thin control surface for the EXISTING backend.
 * Feature 15: sign-in follows the backend's `/auth/config` (development or email +
 * password). The session token lives in memory only (nothing is persisted on the device, so
 * no secure-storage is needed); a 401 or a refused WebSocket session (4401) signs out.
 * Trip state, position, speed and occupancy always come from the backend.
 */
import { StatusBar } from "expo-status-bar";
import { useMemo, useState } from "react";
import { SafeAreaView, StyleSheet } from "react-native";

import { DriverApi } from "./src/api/client";
import { colors } from "./src/components/ui";
import { config } from "./src/config";
import { DriverScreen } from "./src/screens/DriverScreen";
import { LoginScreen } from "./src/screens/LoginScreen";
import { PassengersScreen } from "./src/screens/PassengersScreen";
import { RouteScreen } from "./src/screens/RouteScreen";
import { useDriver } from "./src/state/useDriver";
import { SESSION_ENDED } from "./src/utils/messages";

type View = "drive" | "route" | "passengers";

export default function App() {
  return <AppRoot />;
}

/** The app with an injectable ``fetch`` (tests use a fake backend). */
export function AppRoot({ fetchImpl }: { fetchImpl?: typeof fetch }) {
  const [token, setToken] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const api = useMemo(
    () =>
      new DriverApi({
        baseUrl: config.apiBaseUrl,
        getToken: () => token,
        onUnauthorized: () => {
          setToken(null); // forced sign-out: say why on the sign-in screen
          setNotice(SESSION_ENDED);
        },
        fetchImpl,
      }),
    [token, fetchImpl],
  );
  return (
    <SafeAreaView style={s.root}>
      <StatusBar style="dark" />
      {token ? (
        <SignedIn api={api} onSignOut={() => setToken(null)} />
      ) : (
        <LoginScreen
          api={api}
          notice={notice}
          onSignedIn={(t) => {
            setNotice(null);
            setToken(t);
          }}
        />
      )}
    </SafeAreaView>
  );
}

function SignedIn({ api, onSignOut }: { api: DriverApi; onSignOut: () => void }) {
  const [view, setView] = useState<View>("drive");
  // Poll only while the driving screen is open.
  const state = useDriver(api, { polling: view === "drive" });
  const d = state.data;
  if (view === "route") return <RouteScreen api={api} onBack={() => setView("drive")} />;
  if (view === "passengers" && d?.bus) {
    return (
      <PassengersScreen
        api={api}
        busId={d.bus.id}
        tripId={d.trip?.id ?? null}
        onBack={() => setView("drive")}
      />
    );
  }
  return (
    <DriverScreen
      state={state}
      onViewRoute={() => setView("route")}
      onViewPassengers={() => setView("passengers")}
      onSignOut={onSignOut}
    />
  );
}

const s = StyleSheet.create({ root: { flex: 1, backgroundColor: colors.bg } });
