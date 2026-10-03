/**
 * QR scanner boundary (Feature 8).
 *
 *   QRScanner ── onScan(payload) ──► POST /api/v1/boarding/scan   (the ONLY boarding path)
 *
 * Today the only implementation is the SIMULATED scanner, which builds the payload
 * from the backend's own view of the student (`GET /students/me/boarding`): the
 * signed-in student, their college-ASSIGNED bus and that bus's current trip. A
 * camera scanner can later decode a printed/rotating QR and call the same
 * `onScan` — nothing else changes. PROTOTYPE: the payload is unsigned.
 */
import type { MyBoardingOut, QrPayload } from "../../api/types";

export type OnScan = (payload: QrPayload) => void;

/** Payload for the simulated scan, or null when there is nothing to board. Never user-editable. */
export function simulatedPayload(b: MyBoardingOut, timestampIso: string): QrPayload | null {
  if (b.status !== "assigned" || !b.bus_id || !b.trip_id) return null;
  return {
    student_id: b.student_id,
    bus_id: b.bus_id,
    trip_id: b.trip_id,
    timestamp: timestampIso,
  };
}
