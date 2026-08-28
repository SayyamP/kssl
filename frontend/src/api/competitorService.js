import { apiGet } from "./client";

/* The 31 tracked rivals: sector, HQ, kVA range, CPCB IV+ readiness, assessment.
   Backed by view koel.competitor — a view over koel.snapshot, so it cannot drift from the page. */
export const competitorService = {
  list: (params = "") => apiGet(`/competitors${params}`),
};

export default competitorService;
