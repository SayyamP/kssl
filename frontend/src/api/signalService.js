import { apiGet } from "./client";

/* Overview signal cards across the three pillars.
   Backed by view koel.card — a view over koel.snapshot, so it cannot drift from the page. */
export const signalService = {
  list: (params = "") => apiGet(`/cards${params}`),
};

export default signalService;
