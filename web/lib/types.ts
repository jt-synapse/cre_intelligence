import type { FeatureCollection, MultiPolygon, Polygon } from "geojson";
export type ParcelShape = MultiPolygon | Polygon;
export type Properties = {
  primary_pin: string;
  address: string | null;
  property_id: string | null;
  property_status: string | null;
  property_candidates?: string[];
  county_fips: string;
  relationship_source?: string;
  selected_source?: string;
  related_source?: string;
  control_source?: string;
  related_control_source?: string;
  geometry_version_id: string;
  reader_version: string;
  dataset_key: string;
  observed_at: string;
  projection_generation_id: string;
};
export type Parcels = FeatureCollection<ParcelShape, Properties>;
export type Claim = {
  id: string;
  predicate: string;
  value: unknown;
  verification_state: string;
  observed_at: string;
  source_record_id: string;
  locator: unknown;
  dataset_key: string;
  publisher?: string;
  source_origin?: string;
  attribution?: string;
  content_sha256?: string;
  run_id?: string;
};
export type Parcel = Properties & {
  id: string;
  geometry?: ParcelShape;
  map_destination?: { type: "Point"; coordinates: [number, number] };
  owners: {
    name: string;
    dataset_key: string;
    observed_at: string;
    source_record_id: string;
    verification_state: string;
  }[];
  claims: Claim[];
  screening: unknown[];
};
export type Property = {
  id: string;
  name: string;
  asset_class: string;
  property_status: string;
  parcels: Parcel[];
};
export type Saved = {
  property_id: string;
  name: string;
  property_status: string;
};
export type Organization = { id: string; name: string; role: string };
export type Member = {
  subject: string;
  organizations: Organization[];
  can_curate?: boolean;
};
export function title(v: string) {
  return v.replaceAll("_", " ");
}
export function display(v: unknown): string {
  if (v === null || v === undefined || v === "") return "Unknown";
  if (Array.isArray(v)) return v.map(display).join(" · ");
  if (typeof v === "object")
    return Object.entries(v)
      .map(([k, val]) => title(k) + " " + display(val))
      .join(" · ");
  return String(v);
}
export const emptyParcels: Parcels = {
  type: "FeatureCollection",
  features: [],
};
