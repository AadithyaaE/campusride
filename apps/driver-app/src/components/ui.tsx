/** Large, high-contrast building blocks for a driver glancing at the screen. */
import type { ReactNode } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import type { GpsState } from "../api/client";

export const colors = {
  brand: "#0f3d5e",
  ink: "#0f172a",
  muted: "#475569",
  line: "#cbd5e1",
  bg: "#f8fafc",
  surface: "#ffffff",
  go: "#15803d",
  stop: "#b91c1c",
  warn: "#b45309",
};

export function Field({ label, value, big }: { label: string; value: ReactNode; big?: boolean }) {
  return (
    <View style={styles.field} accessible accessibilityLabel={`${label}: ${String(value)}`}>
      <Text style={styles.label}>{label}</Text>
      <Text style={big ? styles.valueBig : styles.value}>{value}</Text>
    </View>
  );
}

export function BigButton({
  label,
  onPress,
  variant = "primary",
  disabled,
  busy,
}: {
  label: string;
  onPress: () => void;
  variant?: "primary" | "danger" | "secondary";
  disabled?: boolean;
  busy?: boolean;
}) {
  const off = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: !!off, busy: !!busy }}
      disabled={off}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        variant === "secondary"
          ? styles.secondary
          : variant === "danger"
            ? styles.danger
            : styles.primary,
        off && styles.off,
        pressed && styles.pressed,
      ]}
    >
      <Text style={variant === "secondary" ? styles.secondaryText : styles.buttonText}>
        {busy ? "Please wait…" : label}
      </Text>
    </Pressable>
  );
}

const GPS_COLOR: Record<GpsState, string> = {
  LIVE: colors.go,
  STALE: colors.warn,
  UNAVAILABLE: colors.muted,
};

/** GPS state from BACKEND telemetry freshness — always labelled as simulated. */
export function GpsBadge({ gps }: { gps: GpsState }) {
  return (
    <View style={styles.field} accessible accessibilityLabel={`GPS: ${gps}, simulated`}>
      <Text style={styles.label}>GPS</Text>
      <Text style={[styles.value, { color: GPS_COLOR[gps] }]}>● {gps}</Text>
      <Text style={styles.simulated}>SIMULATED GPS</Text>
    </View>
  );
}

export function Banner({ text, tone = "warn" }: { text: string; tone?: "warn" | "error" }) {
  return (
    <View
      accessibilityRole="alert"
      style={[styles.banner, tone === "error" ? styles.bannerError : styles.bannerWarn]}
    >
      <Text style={styles.bannerText}>{text}</Text>
    </View>
  );
}

export const styles = StyleSheet.create({
  field: { marginBottom: 14 },
  label: { fontSize: 13, fontWeight: "700", color: colors.muted, letterSpacing: 1 },
  value: { fontSize: 24, fontWeight: "800", color: colors.ink },
  valueBig: { fontSize: 34, fontWeight: "900", color: colors.ink },
  simulated: { fontSize: 11, fontWeight: "800", color: colors.warn, letterSpacing: 1 },
  button: {
    minHeight: 64,
    borderRadius: 14,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 16,
    marginTop: 12,
  },
  primary: { backgroundColor: colors.go },
  danger: { backgroundColor: colors.stop, minHeight: 76 },
  secondary: {
    backgroundColor: colors.surface,
    borderWidth: 2,
    borderColor: colors.brand,
    minHeight: 52,
  },
  off: { opacity: 0.45 },
  pressed: { opacity: 0.8 },
  buttonText: { color: "#fff", fontSize: 22, fontWeight: "900", letterSpacing: 1 },
  secondaryText: { color: colors.brand, fontSize: 17, fontWeight: "800" },
  banner: { padding: 12, borderRadius: 10, marginBottom: 12 },
  bannerWarn: { backgroundColor: "#fff7ed", borderWidth: 1, borderColor: "#fdba74" },
  bannerError: { backgroundColor: "#fef2f2", borderWidth: 1, borderColor: "#fca5a5" },
  bannerText: { fontSize: 16, fontWeight: "700", color: colors.ink },
});
