/** Read-only passenger count — the Feature 8 backend occupancy (same as students/admins see). */
import { useCallback, useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text } from "react-native";

import type { DriverApi, Occupancy } from "../api/client";
import { Banner, BigButton, colors, Field } from "../components/ui";
import { friendlyError } from "../utils/messages";

interface Props {
  api: DriverApi;
  busId: string;
  tripId: string | null;
  onBack: () => void;
}

export function PassengersScreen({ api, busId, tripId, onBack }: Props) {
  const [occ, setOcc] = useState<Occupancy | null>(null);
  const [boarded, setBoarded] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api.occupancy(busId).then(
      (o) => (setOcc(o), setError(null)),
      (e: unknown) => setError(friendlyError(e, "Passenger count could not be loaded.")),
    );
    if (tripId) {
      api.tripBoarding(tripId).then(
        (b) => setBoarded(b.total_boarded),
        () => setBoarded(null),
      );
    }
  }, [api, busId, tripId]);
  useEffect(load, [load]);

  return (
    <ScrollView contentContainerStyle={s.page}>
      <Text style={s.title}>PASSENGERS · BUS {busId}</Text>
      {error && <Banner text={error} tone="error" />}
      {occ && (
        <>
          <Field label="PASSENGERS" value={`${occ.occupancy} / ${occ.capacity}`} big />
          <Field label="AVAILABLE SEATS" value={occ.available_seats} />
          <Field
            label="OCCUPANCY"
            value={occ.occupancy_percentage === null ? "—" : `${occ.occupancy_percentage}%`}
          />
          {boarded !== null && <Field label="QR BOARDINGS THIS TRIP" value={boarded} />}
          <Text style={s.muted}>
            Synthetic headcount + simulated QR boardings, counted by the backend.
          </Text>
        </>
      )}
      <BigButton label="REFRESH" variant="secondary" onPress={load} />
      <BigButton label="BACK" onPress={onBack} />
    </ScrollView>
  );
}

const s = StyleSheet.create({
  page: { padding: 20, paddingTop: 48, backgroundColor: colors.bg, flexGrow: 1 },
  title: {
    fontSize: 14,
    fontWeight: "800",
    color: colors.muted,
    letterSpacing: 1,
    marginBottom: 12,
  },
  muted: { marginTop: 4, color: colors.muted },
});
