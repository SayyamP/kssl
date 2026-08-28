import { apiGet } from "./client";

/* The 20 tenders in the Market pipeline.
   Backed by view koel.tender — a view over koel.snapshot, so it cannot drift from the page. */
export const tenderService = {
  list: (params = "") => apiGet(`/tenders${params}`),
};

export default tenderService;
