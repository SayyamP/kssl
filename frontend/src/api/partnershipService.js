import { apiGet } from "./client";

/* Rival alliance ties, each flagged when the partner is also KSSL's.
   Backed by view koel.competitor_partner — a view over koel.snapshot, so it cannot drift from the page. */
export const partnershipService = {
  list: (params = "") => apiGet(`/competitor-partners${params}`),
};

export default partnershipService;
