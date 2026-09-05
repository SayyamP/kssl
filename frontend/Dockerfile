# Build the bundle, then serve it from a web server that knows nothing about node.
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
# Blocks the image if invented content reached the bundle. Here rather than in a
# workflow step because BOTH ci.yml and deploy.yml build this image, so the guard
# is unskippable on either path -- and the bundle is the only artefact that
# reflects what a viewer actually sees. Two hand-typed executive rosters passed a
# source review and were found by grepping the DEPLOYED bundle.
# A backslash escape that reached a source file as a literal control byte compiles
# fine and matches nothing, so the fix ships dead and the build stays green. Four
# such bytes were found in this repo on 2026-09-03.
RUN node check_no_control_bytes.mjs
RUN node check_no_fabrication.mjs
RUN node check_no_emoji.mjs
# Only the hermetic tests belong in the image. test_feed_pagination.mjs reads a
# dataset dump that is not in the build context, so gating on it broke the deploy
# -- it stays a local/CI-with-data check.
RUN node test_same_company.mjs && node test_signal_date.mjs && node test_feed_order.mjs && node test_label_case.mjs && node test_headline_case.mjs && node test_fact_label_case.mjs && node test_product_case.mjs && node test_market_facets.mjs && node test_graph_labels.mjs && node test_double_escape.mjs && node test_feed_groups.mjs && node test_feed_page_boundaries.mjs && node test_filter_counts.mjs && node test_geo_map.mjs && node test_global_search.mjs && node test_graph_layout.mjs && node test_signal_text_intact.mjs && node test_source_link.mjs && node test_spec_units.mjs && node test_thumb.mjs && node test_route.mjs && node test_market_tiles.mjs && node test_feed_empty_note.mjs && node test_report_facets.mjs && node test_geo_menu.mjs && node test_revenue_facet.mjs && node test_patent_areas.mjs && node test_rich_text.mjs

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
# Static files plus SPA fallback: every route renders index.html, and Caddy in
# front of this one handles TLS and /api.
RUN printf ':80 {\n\troot * /srv\n\tencode gzip\n\ttry_files {path} /index.html\n\tfile_server\n}\n' > /etc/caddy/Caddyfile
EXPOSE 80
