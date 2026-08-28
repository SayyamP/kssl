import { apiGet } from "./client";

/* The technology pipeline, one row per tracked innovation.
   Backed by view koel.innovation — a view over koel.snapshot, so it cannot drift from the page. */
export const innovationService = {
  list: (params = "") => apiGet(`/innovations${params}`),
};

export default innovationService;
