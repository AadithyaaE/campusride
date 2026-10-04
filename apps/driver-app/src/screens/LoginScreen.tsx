/** Mock driver sign-in (prototype): email only, drivers only. */
import { useState } from "react";
import { StyleSheet, Text, TextInput, View } from "react-native";

import type { DriverApi } from "../api/client";
import { Banner, BigButton, colors } from "../components/ui";
import { friendlyError } from "../utils/messages";

export const DEMO_DRIVER_EMAIL = "driver07@campusride.demo";

export function LoginScreen({
  api,
  onSignedIn,
}: {
  api: DriverApi;
  onSignedIn: (token: string) => void;
}) {
  const [email, setEmail] = useState(DEMO_DRIVER_EMAIL);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const signIn = async () => {
    setBusy(true);
    setError(null);
    try {
      const t = await api.mockLogin(email.trim());
      const me = await api.me(t.access_token);
      if (me.role !== "driver") {
        setError("This app is for drivers only.");
        return;
      }
      onSignedIn(t.access_token);
    } catch (e) {
      setError(friendlyError(e, "Sign-in failed. Check the email and try again."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={s.page}>
      <Text style={s.brand}>CampusRide Driver</Text>
      <Text style={s.muted}>Mock sign-in for the prototype — no password.</Text>
      <Text style={s.label}>Driver email</Text>
      <TextInput
        accessibilityLabel="Driver email"
        style={s.input}
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        keyboardType="email-address"
      />
      {error && <Banner text={error} tone="error" />}
      <BigButton label="SIGN IN" busy={busy} onPress={() => void signIn()} />
    </View>
  );
}

const s = StyleSheet.create({
  page: { flex: 1, padding: 20, paddingTop: 72, backgroundColor: colors.bg },
  brand: { fontSize: 28, fontWeight: "900", color: colors.brand },
  muted: { color: colors.muted, marginBottom: 24 },
  label: { fontSize: 13, fontWeight: "700", color: colors.muted, letterSpacing: 1 },
  input: {
    fontSize: 18,
    padding: 14,
    borderRadius: 10,
    borderWidth: 2,
    borderColor: colors.line,
    backgroundColor: colors.surface,
    marginTop: 6,
    marginBottom: 12,
  },
});
