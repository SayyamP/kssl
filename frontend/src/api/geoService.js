import { apiGet } from "./client";

/* Footprint rows: who sells what, where, and on what activity.
   Backed by view koel.geo_presence — a view over koel.snapshot, so it cannot drift from the page. */
export const geoService = {
  list: (params = "") => apiGet(`/geo${params}`),
};

export default geoService;
