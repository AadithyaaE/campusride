/**
 * Friendly aliases over the types GENERATED from the backend's OpenAPI schema
 * (`schema.gen.ts`, regenerate with `npm run gen:api` while the backend runs).
 * Never hand-edit field lists here — change the backend contract instead.
 */
import type { components } from "./schema.gen";

type Schemas = components["schemas"];

export type HealthOut = Schemas["HealthOut"];
export type ClockOut = Schemas["ClockOut"];
export type TokenOut = Schemas["TokenOut"];
export type MeOut = Schemas["MeOut"];
export type Role = Schemas["Role"];
export type Direction = Schemas["Direction"];
export type GeoPoint = Schemas["GeoPoint"];
export type LineString = Schemas["LineString"];
export type StopOut = Schemas["StopOut"];
export type NearbyStopOut = Schemas["NearbyStopOut"];
export type StopServiceOut = Schemas["StopServiceOut"];
export type RouteSummaryOut = Schemas["RouteSummaryOut"];
export type DirectionSummaryOut = Schemas["DirectionSummaryOut"];
export type RouteDetailOut = Schemas["RouteDetailOut"];
export type RouteDirectionOut = Schemas["RouteDirectionOut"];
export type RouteStopOut = Schemas["RouteStopOut"];
export type MyAssignmentOut = Schemas["MyAssignmentOut"];
export type AssignmentOut = Schemas["AssignmentOut"];
export type BusOut = Schemas["BusOut"];
export type BusLiveOut = Schemas["BusLiveOut"];
export type BusDetailOut = Schemas["BusDetailOut"];
export type BusStatus = Schemas["BusStatus"];
export type SimStatusOut = Schemas["SimStatusOut"];
export type StopBusOut = Schemas["StopBusOut"];
export type StopBusesOut = Schemas["StopBusesOut"];
export type MyStopBusesOut = Schemas["MyStopBusesOut"];
export type StopProximity = Schemas["StopProximity"];
export type EtaPredictionOut = Schemas["EtaPredictionOut"];
export type ArrivalOut = Schemas["ArrivalOut"];
export type StopArrivalsOut = Schemas["StopArrivalsOut"];
export type MyArrivalsOut = Schemas["MyArrivalsOut"];
export type BusEtaOut = Schemas["BusEtaOut"];
export type BusOptionOut = Schemas["BusOptionOut"];
export type BusOptionsOut = Schemas["BusOptionsOut"];
export type CommuteDecisionOut = Schemas["CommuteDecisionOut"];
// ---- QR boarding + live occupancy (Feature 8)
/** What a boarding QR carries (PROTOTYPE: unsigned, from a simulated scanner). */
export type BoardingScanIn = Schemas["BoardingScanIn"];
export type QrPayload = Pick<BoardingScanIn, "student_id" | "bus_id" | "trip_id" | "timestamp">;
/** What `POST /boarding/scan` accepts: the QR payload + optional stop / scanner kind. */
export type BoardingScanRequest = QrPayload & Partial<Pick<BoardingScanIn, "stop_id" | "scanner">>;
export type BoardingScanOut = Schemas["BoardingScanOut"];
export type BoardingEventOut = Schemas["BoardingEventOut"];
export type OccupancyOut = Schemas["OccupancyOut"];
export type TripBoardingOut = Schemas["TripBoardingOut"];
export type MyBoardingOut = Schemas["MyBoardingOut"];
// ---- missed-bus recovery (Feature 9) — suggestions only, never a reassignment
export type RecoveryOut = Schemas["RecoveryOut"];
export type RecoveryOptionOut = Schemas["RecoveryOptionOut"];
// ---- route deviation (Feature 10) — evaluated by the backend, displayed as given
export type RouteStatus = Schemas["RouteStatus"];
export type RouteStatusResponse = Schemas["RouteStatusOut"];
export type RouteDeviationDemoMode = Schemas["RouteDeviationIn"]["mode"];
// ---- in-app alerts (Feature 11) — created by the backend, displayed as given
export type Alert = Schemas["AlertOut"];
export type AlertType = Schemas["AlertType"];
export type AlertSeverity = Schemas["Severity"];
export type AlertsResponse = Alert[];
/** Backend commute decision (Feature 7); YES / RISK / MISSED are the decisions. */
export type CommuteDecision = NonNullable<CommuteDecisionOut["decision"]>;
/** Backend comparison indicator (Feature 6). */
export type BusIndicator = BusOptionOut["indicators"][number];

/** GeoJSON coordinate order used by the backend: [longitude, latitude]. */
export type LngLat = GeoPoint["coordinates"];
