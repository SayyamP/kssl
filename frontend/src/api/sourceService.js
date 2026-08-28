import { apiGet } from "./client";

/* The URL registry every sourced claim on the page points at.
   Backed by view koel.source — a view over koel.snapshot, so it cannot drift from the page. */
export const sourceService = {
  list: (params = "") => apiGet(`/sources${params}`),
};

export default sourceService;
