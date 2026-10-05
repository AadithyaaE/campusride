/**
 * The driving screen. Idle (READY) shows the bus, route and first stop with one dominant
 * START TRIP; DRIVING shows the few live values a driver needs with one dominant STOP TRIP.
 * Every value is the backend's (`GET /driver/me`); the screen only renders it.
 */
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import type { DriverState } from "../state/useDriver";
import { Banner, BigButton, colors, Field, GpsBadge } from "../components/ui";
import { campusTime, ROUTE_STATUS_LABEL, TRIP_LABEL } from "../utils/format";

const CONNECTION: Record<DriverState["realtime"], string> = {
  live: "Connected",
  connecting: "Connecting…",
  offline: "Reconnecting…",
};

interface Props {
  state: DriverState;
  onViewRoute: () => void;
  onViewPassengers: () => void;
  onSignOut: () => void;
}

export function DriverScreen({ state, onViewRoute, onViewPassengers, onSignOut }: Props) {
  const { data: d, error, actionError, busy, act, refresh, realtime } = state;
  const driving = d?.trip_state === "ACTIVE";
  return (
    <ScrollView contentContainerStyle={s.page}>
      <View style={s.header}>
        <Text style={s.brand}>CampusRide Driver</Text>
        <View
          style={[s.pill, realtime === "live" ? s.pillLive : s.pillWait]}
          accessible
          accessibilityLabel={`Connection: ${CONNECTION[realtime]}`}
        >
          <View style={[s.dot, realtime === "live" ? s.dotLive : s.dotWait]} />
          <Text style={[s.pillText, realtime === "live" ? s.pillTextLive : null]}>
            {CONNECTION[realtime]}
          </Text>
        </View>
        <Pressable accessibilityRole="button" onPress={onSignOut} hitSlop={12}>
          <Text style={s.link}>Sign out</Text>
        </Pressable>
      </View>

      {realtime === "offline" && d && (
        <Banner text="Connection lost. Trying to reconnect — the screen updates when it's back." />
      )}
      {error && <Banner text={error} tone="error" />}
      {actionError && <Banner text={actionError} />}

      {!d ? (
        error ? (
          <BigButton label="TRY AGAIN" variant="secondary" onPress={() => void refresh()} />
        ) : (
          <View style={s.loading}>
            <ActivityIndicator accessibilityLabel="Loading" size="large" color={colors.brand} />
            <Text style={s.muted}>Getting your trip…</Text>
          </View>
        )
      ) : (
        <>
          <View style={s.hero}>
            <Text style={s.heroBus} accessibilityRole="header">
              {d.bus ? `BUS ${d.bus.number}` : "NO BUS"}
            </Text>
            <Text style={s.heroDriver}>{d.driver.name}</Text>
            {d.route && <Text style={s.heroRoute}>{d.route.label ?? d.route.name}</Text>}
          </View>

          <View
            style={[s.status, driving ? s.statusDriving : null]}
            accessible
            accessibilityLabel={`Trip status: ${TRIP_LABEL[d.trip_state] ?? d.trip_state}`}
          >
            <Text style={s.statusLabel}>TRIP STATUS</Text>
            <Text style={[s.statusValue, driving ? s.active : null]}>
              {TRIP_LABEL[d.trip_state] ?? d.trip_state}
            </Text>
          </View>

          {d.message && <Banner text={d.message} />}

          {driving ? (
            <>
              {d.live?.current_stop && <Field label="CURRENT STOP" value={d.live.current_stop} />}
              {d.next_stop && <Field label="NEXT STOP" value={d.next_stop} big />}
              <Field
                label="PASSENGERS"
                value={
                  d.live
                    ? `${d.live.occupancy} / ${d.live.capacity} · ${d.live.available_seats} seats free`
                    : "—"
                }
              />
              {d.can_stop && (
                <BigButton
                  label="STOP TRIP"
                  variant="danger"
                  busy={busy === "stop"}
                  disabled={busy !== null}
                  onPress={() => void act("stop")}
                />
              )}
              <View style={s.row}>
                <View style={s.half}>
                  <BigButton label="VIEW ROUTE" variant="secondary" onPress={onViewRoute} />
                </View>
                <View style={s.half}>
                  <BigButton label="PASSENGERS" variant="secondary" onPress={onViewPassengers} />
                </View>
              </View>

              <View style={s.details}>
                <Text style={s.detailsHead}>TRIP DETAILS</Text>
                <View style={s.row}>
                  <View style={s.half}>
                    <Field label="SPEED" value={d.live ? `${d.live.speed_kmh} km/h` : "—"} />
                  </View>
                  <View style={s.half}>
                    <Field
                      label="ROUTE STATUS"
                      value={
                        d.live?.route_status
                          ? (ROUTE_STATUS_LABEL[d.live.route_status] ?? d.live.route_status)
                          : "—"
                      }
                    />
                  </View>
                </View>
                <GpsBadge gps={d.gps} />
                <BigButton
                  label="SIMULATE GPS"
                  variant="secondary"
                  busy={busy === "gps"}
                  disabled={busy !== null}
                  onPress={() => void act("gps")}
                />
              </View>
            </>
          ) : (
            <>
              {d.next_stop && <Field label="FIRST STOP" value={d.next_stop} big />}
              {d.trip && d.trip_state === "READY" && (
                <View style={s.small}>
                  <Text style={s.smallText}>
                    Departs {campusTime(d.trip.scheduled_start)} · Capacity {d.bus?.capacity ?? "—"}{" "}
                    seats
                  </Text>
                </View>
              )}
              {d.can_start && (
                <BigButton
                  label="START TRIP"
                  busy={busy === "start"}
                  disabled={busy !== null}
                  onPress={() => void act("start")}
                />
              )}
              {d.bus && <BigButton label="VIEW ROUTE" variant="secondary" onPress={onViewRoute} />}
              {d.bus && (
                <View style={s.details}>
                  <GpsBadge gps={d.gps} />
                </View>
              )}
            </>
          )}
        </>
      )}
      <Text style={s.foot}>
        Demo GPS from the CampusRide simulator — your phone&apos;s location is not used.
      </Text>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  page: { padding: 20, paddingTop: 48, backgroundColor: colors.bg, flexGrow: 1 },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 8,
    marginBottom: 18,
  },
  brand: { fontSize: 18, fontWeight: "900", color: colors.brand, flexShrink: 1 },
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
    borderWidth: 1,
  },
  pillLive: { backgroundColor: "#f0fdf4", borderColor: "#86efac" },
  pillWait: { backgroundColor: "#fffbeb", borderColor: "#fcd34d" },
  dot: { width: 8, height: 8, borderRadius: 4 },
  dotLive: { backgroundColor: colors.go },
  dotWait: { backgroundColor: colors.warn },
  pillText: { fontSize: 13, fontWeight: "700", color: colors.warn },
  pillTextLive: { color: colors.go },
  link: { fontSize: 15, fontWeight: "700", color: colors.brand, textDecorationLine: "underline" },
  loading: { alignItems: "center", gap: 12, marginTop: 40 },
  muted: { color: colors.muted, fontSize: 15 },
  hero: {
    padding: 18,
    borderRadius: 16,
    backgroundColor: colors.brand,
    marginBottom: 14,
  },
  heroBus: { fontSize: 40, fontWeight: "900", color: "#fff", letterSpacing: 1 },
  heroDriver: { fontSize: 18, fontWeight: "700", color: "#e2e8f0", marginTop: 2 },
  heroRoute: { fontSize: 15, color: "#cbd5e1", marginTop: 4 },
  status: {
    padding: 14,
    borderRadius: 14,
    backgroundColor: colors.surface,
    borderWidth: 2,
    borderColor: colors.line,
    marginBottom: 16,
  },
  statusDriving: { borderColor: colors.go, backgroundColor: "#f0fdf4" },
  statusLabel: { fontSize: 13, fontWeight: "700", color: colors.muted, letterSpacing: 1 },
  statusValue: { fontSize: 32, fontWeight: "900", color: colors.ink },
  active: { color: colors.go },
  row: { flexDirection: "row", gap: 10 },
  half: { flex: 1 },
  small: { marginBottom: 6 },
  smallText: { fontSize: 15, color: colors.muted },
  details: {
    marginTop: 22,
    paddingTop: 14,
    borderTopWidth: 1,
    borderTopColor: colors.line,
  },
  detailsHead: {
    fontSize: 12,
    fontWeight: "800",
    color: colors.muted,
    letterSpacing: 1,
    marginBottom: 10,
  },
  foot: { marginTop: 24, fontSize: 12, color: colors.muted, textAlign: "center" },
});
