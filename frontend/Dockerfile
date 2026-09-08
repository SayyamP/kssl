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
# esbuild does not resolve free identifiers -- an unbound name is assumed to be a
# runtime global -- so a call to a function that has never existed builds green and
# throws only when that line runs. formatTitleCase sat in a useMemo in Products.jsx
# and took the whole view down on staging, past `npm run build` and every check
# below it. Runs first because it is the cheapest and the most fundamental: nothing
# further is worth checking about code that cannot execute.
RUN node check_no_undefined_names.mjs
RUN node check_no_control_bytes.mjs
RUN node check_no_fabrication.mjs
RUN node check_no_emoji.mjs
# Only the hermetic tests belong in the image. test_feed_pagination.mjs reads a
# dataset dump that is not in the build context, so gating on it broke the deploy
# -- it stays a local/CI-with-data check.
RUN node test_same_company.mjs && node test_signal_date.mjs && node test_feed_order.mjs && node test_label_case.mjs && node test_headline_case.mjs && node test_fact_label_case.mjs && node test_product_case.mjs && node test_market_facets.mjs && node test_graph_labels.mjs && node test_double_escape.mjs && node test_feed_empty_note.mjs && node test_feed_groups.mjs && node test_feed_page_boundaries.mjs && node test_feed_state.mjs && node test_filter_counts.mjs && node test_geo_map.mjs && node test_geo_menu.mjs && node test_global_search.mjs && node test_graph_layout.mjs && node test_innovation_view.mjs && node test_market_tiles.mjs && node test_patent_areas.mjs && node test_report_facets.mjs && node test_revenue_facet.mjs && node test_rich_text.mjs && node test_route.mjs && node test_signal_text_intact.mjs && node test_source_link.mjs && node test_spec_units.mjs && node test_tender_row.mjs && node test_thumb.mjs && node test_statements.mjs && node test_origin_filter.mjs && node test_feed_split.mjs && node test_news_trail.mjs

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
# Static files plus SPA fallback: every route renders index.html, and Caddy in
# front of this one handles TLS and /api.
# try_files also probes {path}/index.html BEFORE the SPA fallback, so a real
# subdirectory page (e.g. the operator dashboard at /ops/) is served instead of
# being rewritten to the root app's index.html. Without the middle term, /ops/
# fell through to the SPA and showed the main app; /ops/index.html worked but
# the bare directory URL did not.
# CACHE THE HASHED FILES, NEVER THE FILE THAT NAMES THEM.
#
# Nothing here set a cache header, so index.html was cached by whatever heuristic the
# browser and the CDN in front of it chose. index.html is the ONLY unhashed file --
# vite renames the bundle on every build, so /assets/index-<hash>.js is a new URL each
# time and can never be served stale. Caching the one file that NAMES those bundles
# pins a viewer to the previous build's asset names, so a deploy that succeeded in
# every other respect still shows the old app until somebody hard-reloads.
#
# Measured on staging 2026-09-08: the severity badge shipped, the served bundle
# contained `sevtag`, the served CSS contained `.sevtag.high`, and /api/dataset
# returned a severity on 477 of 939 cards -- and the page showed none of it. That is
# indistinguishable from a failed deploy, and the natural next move is to deploy
# again, which looks broken too.
#
# Mutually exclusive matchers rather than a default plus an override, so there is no
# question of which rule wins for a hashed asset.
RUN printf ':80 {\n\troot * /srv\n\tencode gzip\n\t@assets path /assets/*\n\t@rest not path /assets/*\n\theader @assets Cache-Control \"public, max-age=31536000, immutable\"\n\theader @rest Cache-Control \"no-cache\"\n\ttry_files {path} {path}/index.html /index.html\n\tfile_server\n}\n' > /etc/caddy/Caddyfile
EXPOSE 80
