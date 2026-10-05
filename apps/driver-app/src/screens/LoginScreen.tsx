/**
 * Driver sign-in (Feature 15). The backend's `GET /auth/config` decides the form:
 * development sign-in (email only, clearly labelled) or email + password. Drivers only.
 * The password is sent once and never kept; only the backend token is held (in memory).
 */
import { useEffect, useState } from "react";
import { StyleSheet, Text, TextInput, View } from "react-native";

import { ApiError, type AuthConfig, type DriverApi } from "../api/client";
import { Banner, BigButton, colors } from "../components/ui";
import { friendlyError } from "../utils/messages";

export const DEMO_DRIVER_EMAIL = "driver07@campusride.demo";

export function LoginScreen({
  api,
  notice = null,
  onSignedIn,
}: {
  api: DriverApi;
  /** Why the driver is here again (e.g. the session ended). */
  notice?: string | null;
  onSignedIn: (token: string) => void;
}) {
  const [cfg, setCfg] = useState<AuthConfig | null>(null);
  const [email, setEmail] = useState(DEMO_DRIVER_EMAIL);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .authConfig()
      .then(setCfg, (e: unknown) => setError(friendlyError(e, "Connection unavailable")));
  }, [api]);

  const signIn = async () => {
    if (!cfg) return;
    setBusy(true);
    setError(null);
    try {
      const t = cfg.password_login
        ? await api.passwordLogin(email.trim(), password)
        : await api.devLogin(email.trim());
      const me = await api.me(t.access_token);
      if (me.role !== "driver") {
        setError("This app is for drivers only.");
        return;
      }
      onSignedIn(t.access_token);
    } catch (e) {
      // a refused sign-in says why (wrong password / disabled account), not "session ended"
      setError(
        e instanceof ApiError && e.status === 401
          ? e.message
          : friendlyError(e, "Sign-in failed. Check your details and try again."),
      );
    } finally {
      setPassword("");
      setBusy(false);
    }
  };

  const usable = cfg !== null && (cfg.dev_login || cfg.password_login);
  return (
    <View style={s.page}>
      <Text style={s.brand}>CampusRide Driver</Text>
      <Text style={s.tagline}>Sign in to start your trip.</Text>
      {notice && <Banner text={notice} />}
      {!cfg && !error && <Text style={s.muted}>Checking sign-in options…</Text>}
      {cfg?.development && (
        <Text style={s.dev} accessibilityRole="text">
          Demo sign-in — use the demo driver account. No password is needed in this demo
          environment.
        </Text>
      )}
      {cfg?.external_provider && (
        <Text style={s.muted}>
          Your organisation&apos;s sign-in isn&apos;t available in this app yet. Please contact the
          transport office.
        </Text>
      )}
      {usable && (
        <>
          <Text style={s.label}>Driver email</Text>
          <TextInput
            accessibilityLabel="Driver email"
            style={s.input}
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            keyboardType="email-address"
          />
        </>
      )}
      {cfg?.password_login && (
        <>
          <Text style={s.label}>Password</Text>
          <TextInput
            accessibilityLabel="Password"
            style={s.input}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            autoCapitalize="none"
            autoComplete="current-password"
          />
        </>
      )}
      {error && <Banner text={error} tone="error" />}
      <BigButton label="SIGN IN" busy={busy} disabled={!usable} onPress={() => void signIn()} />
    </View>
  );
}

const s = StyleSheet.create({
  page: { flex: 1, padding: 20, paddingTop: 72, backgroundColor: colors.bg },
  brand: { fontSize: 28, fontWeight: "900", color: colors.brand },
  tagline: { fontSize: 16, color: colors.muted, marginTop: 4, marginBottom: 16 },
  muted: { color: colors.muted, marginBottom: 24 },
  dev: {
    marginVertical: 16,
    padding: 10,
    borderRadius: 8,
    backgroundColor: "#fff4e5",
    color: "#6b3d00",
    fontWeight: "600",
  },
  label: { fontSize: 13, fontWeight: "700", color: colors.muted, letterSpacing: 1, marginTop: 8 },
  input: {
    fontSize: 18,
    padding: 14,
    borderRadius: 10,
    borderWidth: 2,
    borderColor: colors.line,
    backgroundColor: colors.surface,
    marginTop: 6,
    marginBottom: 18,
  },
});
