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
/** Backend commute decision (Feature 7); YES / RISK / MISSED are the decisions. */
export type CommuteDecision = NonNullable<CommuteDecisionOut["decision"]>;
/** Backend comparison indicator (Feature 6). */
export type BusIndicator = BusOptionOut["indicators"][number];

/** GeoJSON coordinate order used by the backend: [longitude, latitude]. */
export type LngLat = GeoPoint["coordinates"];
