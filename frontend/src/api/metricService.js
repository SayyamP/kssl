import { apiGet } from "./client";

/* The small config maps (category keys, relation labels, activity labels).
   Backed by view koel.lookup — a view over koel.snapshot, so it cannot drift from the page. */
export const metricService = {
  list: (params = "") => apiGet(`/lookups${params}`),
};

export default metricService;
