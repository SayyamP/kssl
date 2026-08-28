import { apiGet } from "./client";

/* The 697 rating-matched KSSL-vs-rival product pairs behind Positioning.
   Backed by view koel.matchup — a view over koel.snapshot, so it cannot drift from the page. */
export const matchupService = {
  list: (params = "") => apiGet(`/matchups${params}`),
};

export default matchupService;
