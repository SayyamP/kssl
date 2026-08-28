import { apiGet } from "./client";

/* The dashboard's bootstrap read: every global in koel.snapshot, in one round trip.
   The derived numbers (edge index, gap model, geo overlap, graph layout) are
   corpus-wide — they need the whole matchup and competitor set to compute at all —
   so this is the honest shape of the read, not a shortcut around the other routes. */
export const datasetService = {
  getDataset: (options) => apiGet("/dataset", options),
  getGlobal: (name, options) =>
    apiGet(`/globals/${encodeURIComponent(name)}`, options),
  health: (options) => apiGet("/health", options),
  manifest: (options) => apiGet("/manifest", options),
};

export default datasetService;
