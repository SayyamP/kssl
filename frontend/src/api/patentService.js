import { apiGet } from "./client";

/* Competitor patent filings, deduped by patent number.
   Backed by view koel.patent — a view over koel.snapshot, so it cannot drift from the page. */
export const patentService = {
  list: (params = "") => apiGet(`/patents${params}`),
};

export default patentService;
