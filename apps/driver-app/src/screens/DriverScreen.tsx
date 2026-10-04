/**
 * The driving screen. Idle (READY) shows who/what/where with one dominant START TRIP;
 * ACTIVE shows the few live values a driver needs with one dominant STOP TRIP.
 * Every value is the backend's (`GET /driver/me`); the screen only renders it.
 */
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import type { DriverState } from "../state/useDriver";
import { Banner, BigButton, colors, Field, GpsBadge } from "../components/ui";
import { campusTime, ROUTE_STATUS_LABEL, TRIP_LABEL } from "../utils/format";

const FEED: Record<DriverState["realtime"], string> = {
  live: "● LIVE",
  connecting: "○ CONNECTING",
  offline: "○ RECONNECTING",
};

interface Props {
  state: DriverState;
  onViewRoute: () => void;
  onViewPassengers: () => void;
  onSignOut: () => void;
}

export function DriverScreen({ state, onViewRoute, onViewPassengers, onSignOut }: Props) {
  const { data: d, error, actionError, busy, act, refresh, realtime } = state;
  return (
    <ScrollView contentContainerStyle={s.page}>
      <View style={s.header}>
        <Text style={s.brand}>CampusRide Driver</Text>
        <Text
          style={[s.feed, realtime === "live" ? s.feedLive : null]}
          accessibilityLabel={`Live updates: ${FEED[realtime]}`}
        >
          {FEED[realtime]}
        </Text>
        <Pressable accessibilityRole="button" onPress={onSignOut}>
          <Text style={s.link}>Sign out</Text>
        </Pressable>
      </View>

      {error && <Banner text={error} tone="error" />}
      {actionError && <Banner text={actionError} />}

      {!d ? (
        error ? (
          <BigButton label="TRY AGAIN" variant="secondary" onPress={() => void refresh()} />
        ) : (
          <ActivityIndicator accessibilityLabel="Loading" size="large" color={colors.brand} />
        )
      ) : (
        <>
          <Field label="DRIVER" value={d.driver.name} big />
          <View style={s.status} accessible accessibilityLabel={`Trip status: ${d.trip_state}`}>
            <Text style={s.statusLabel}>TRIP STATUS</Text>
            <Text style={[s.statusValue, d.trip_state === "ACTIVE" ? s.active : null]}>
              {TRIP_LABEL[d.trip_state] ?? d.trip_state}
            </Text>
          </View>

          {d.message && <Banner text={d.message} />}

          {d.bus && (
            <Field
              label={d.trip_state === "ACTIVE" ? "BUS" : "ASSIGNED BUS"}
              value={`Bus ${d.bus.number}`}
            />
          )}
          {d.route && <Field label="ROUTE" value={d.route.label ?? d.route.name} />}
          {d.next_stop && <Field label="NEXT STOP" value={d.next_stop} big />}

          {d.trip_state === "ACTIVE" ? (
            <>
              <Field label="SPEED" value={d.live ? `${d.live.speed_kmh} km/h` : "—"} />
              <GpsBadge gps={d.gps} />
              <Field
                label="PASSENGERS"
                value={d.live ? `${d.live.occupancy} / ${d.live.capacity}` : "—"}
              />
              <Field
                label="ROUTE STATUS"
                value={
                  d.live?.route_status
                    ? (ROUTE_STATUS_LABEL[d.live.route_status] ?? d.live.route_status)
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
              <BigButton
                label="SIMULATE GPS"
                variant="secondary"
                busy={busy === "gps"}
                disabled={busy !== null}
                onPress={() => void act("gps")}
              />
              <View style={s.row}>
                <View style={s.half}>
                  <BigButton label="VIEW ROUTE" variant="secondary" onPress={onViewRoute} />
                </View>
                <View style={s.half}>
                  <BigButton label="PASSENGERS" variant="secondary" onPress={onViewPassengers} />
                </View>
              </View>
            </>
          ) : (
            <>
              {d.trip && d.trip_state === "READY" && (
                <View style={s.small}>
                  <Text style={s.smallText}>
                    Today’s trip {d.trip.id} · departs {campusTime(d.trip.scheduled_start)}
                  </Text>
                  <Text style={s.smallText}>
                    First stop {d.trip.first_stop ?? "—"} · Capacity {d.bus?.capacity ?? "—"}
                  </Text>
                </View>
              )}
              {d.bus && <GpsBadge gps={d.gps} />}
              {d.can_start && (
                <BigButton
                  label="START TRIP"
                  busy={busy === "start"}
                  disabled={busy !== null}
                  onPress={() => void act("start")}
                />
              )}
              {d.bus && <BigButton label="VIEW ROUTE" variant="secondary" onPress={onViewRoute} />}
            </>
          )}
        </>
      )}
      <Text style={s.foot}>
        Prototype · synthetic GPS from the CampusRide simulator · no phone GPS is used
      </Text>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  feed: { fontSize: 12, fontWeight: "700", color: colors.muted, letterSpacing: 1 },
  feedLive: { color: "#15803d" },
  page: { padding: 20, paddingTop: 48, backgroundColor: colors.bg, flexGrow: 1 },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 18,
  },
  brand: { fontSize: 18, fontWeight: "900", color: colors.brand },
  link: { fontSize: 15, fontWeight: "700", color: colors.brand, textDecorationLine: "underline" },
  status: {
    padding: 14,
    borderRadius: 14,
    backgroundColor: colors.surface,
    borderWidth: 2,
    borderColor: colors.line,
    marginBottom: 16,
  },
  statusLabel: { fontSize: 13, fontWeight: "700", color: colors.muted, letterSpacing: 1 },
  statusValue: { fontSize: 32, fontWeight: "900", color: colors.ink },
  active: { color: colors.go },
  row: { flexDirection: "row", gap: 10 },
  half: { flex: 1 },
  small: { marginBottom: 10 },
  smallText: { fontSize: 14, color: colors.muted },
  foot: { marginTop: 24, fontSize: 12, color: colors.muted, textAlign: "center" },
});
