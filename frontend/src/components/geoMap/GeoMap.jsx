import { useEffect, useMemo, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { companyOrigin } from "../../lib/countryFacet.js";
/* The country table, the plot plan and the head-office rule moved to lib/geoCountries.js
   so a node test can import them instead of slicing this file's text. Re-exported below
   because pages/competitive/Geo.jsx and test_geo_map.mjs read them from here. */
import {
  geoCountryCoords,
  geoPlotPlan,
  isHeadOffice,
} from "../../lib/geoCountries.js";
/* The tooltip's wording, as data: lib/geoBadge.js. See the comments there for the three
   faults it exists to prevent -- the badge that parroted the client's own name, the
   estimate drawn as a measurement, and the head office that never matched. */
import {
  clientFootprintNote,
  companyRole,
  presenceBadge,
} from "../../lib/geoBadge.js";

export { geoCountryCoords, geoPlotPlan };

// Emptied deliberately. This map held hand-researched export/import strings per company --
// data, living in code, that no source in the corpus supports. The pipeline now supplies
// everything the map draws, and a company with nothing recorded shows nothing rather than
// showing a sentence somebody typed in 2026.
const COMPANY_MATERIALS = {};

/* The plotted list comes from the SERVED footprint rows — geoCountries is a
   vocabulary that at most orders them. An empty geoData plots an empty map. */
export function servedGeoCountries(data) {
  const served = new Set();
  Object.values(data.geoData || {}).forEach((byCountry) =>
    Object.keys(byCountry || {}).forEach((ct) => served.add(ct)),
  );
  const order = data.geoCountries || [];
  return [...served].sort((a, b) => {
    const ia = order.indexOf(a);
    const ib = order.indexOf(b);
    return (ia < 0 ? 1 : 0) - (ib < 0 ? 1 : 0) || ia - ib || a.localeCompare(b);
  });
}

/* Basemap tiles.

   CARTO's dark_all served this map keylessly for years and now returns a tile
   stamped "API KEY REQUIRED · carto.com/basemaps/apikey" instead of the map — a 200
   with a watermark, not an error, which is why the map went on rendering markers over
   an unreadable ground rather than failing loudly.

   The default below is Esri's World Dark Gray Canvas: a dark basemap that needs no key
   and no account. If a CARTO (or Stadia, or MapTiler) key is ever bought, set both
   VITE_MAP_TILE_URL and VITE_MAP_TILE_ATTR at BUILD time — Vite inlines them, so they
   must be present when the image is built, not when the container starts. e.g.
     VITE_MAP_TILE_URL="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png?api_key=KEY"
   Attribution is a licence condition on every one of these providers, so the URL and
   the credit move together. */
const TILE_URL =
  import.meta.env.VITE_MAP_TILE_URL ||
  "https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}";
const TILE_ATTR =
  import.meta.env.VITE_MAP_TILE_ATTR ||
  '&copy; <a href="https://www.esri.com/">Esri</a> &copy; OpenStreetMap contributors';

/* Countries the pipeline serves that the map did not draw, named rather than hidden.
   Silence here would be indistinguishable from "we have no rows there", which is the
   confusion the hashed coordinates created in the first place. */
function GeoUnplotted({ countries }) {
  const { regions, unlocated } = geoPlotPlan(countries);
  if (!regions.length && !unlocated.length) return null;
  const parts = [];
  if (unlocated.length)
    parts.push(`${unlocated.length} without map coordinates: ${unlocated.join(", ")}`);
  if (regions.length) parts.push(`regional rows, not pinned: ${regions.join(", ")}`);
  return (
    <div className="geo-map-unplotted">
      {parts.join(" \u00b7 ")}
    </div>
  );
}

/* THE CLIENT'S OWN FOOTPRINT, in words. See clientFootprintNote in lib/geoBadge.js:
   the map draws one green dot over India and the reader concludes "KSSL is India only",
   because the Europe row is a continent that is deliberately not pinned and the Saudi
   Arabia row is an analytical estimate. Both of those are correct on their own; neither
   is visible. */
function GeoClientFootprint({ data }) {
  const clientRow = (data.geoComps || []).find((c) => c.isBf);
  const ownByCountry =
    (data.geoData &&
      (data.geoData[clientRow?.id] || data.geoData[data.client?.short || "KSSL"])) ||
    {};
  const clientLabel = (data.client && (data.client.short || data.client.name)) || "KSSL";
  const note = clientFootprintNote({
    clientLabel,
    ownByCountry,
    plan: geoPlotPlan(Object.keys(ownByCountry)),
  });
  return note ? <div className="geo-map-client-footprint">{note}</div> : null;
}

export default function GeoMap({ data, geo, selectedCountry, onSelectCountry }) {
  const mapContainerRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const countries = useMemo(() => servedGeoCountries(data), [data]);

  useEffect(() => {
    if (!mapContainerRef.current) return;

    if (!mapInstanceRef.current) {
      const map = L.map(mapContainerRef.current, {
        center: [18, 10],
        zoom: 2.6,
        minZoom: 2.5,
        maxZoom: 8,
        zoomSnap: 0.1,
        zoomControl: true,
        dragging: true,
        touchZoom: true,
        doubleClickZoom: true,
        scrollWheelZoom: true,
        boxZoom: true,
        keyboard: true,
        worldCopyJump: false,
        maxBounds: [
          [-85, -180],
          [85, 180],
        ],
        maxBoundsViscosity: 1.0,
      });

      L.tileLayer(TILE_URL, {
        attribution: TILE_ATTR,
        subdomains: "abcd",
        maxZoom: 19,
        noWrap: true,
        bounds: [
          [-85, -180],
          [85, 180],
        ],
      }).addTo(map);

      mapInstanceRef.current = map;
    }

    const map = mapInstanceRef.current;

    map.eachLayer((layer) => {
      if (layer instanceof L.CircleMarker) {
        map.removeLayer(layer);
      }
    });

    const plan = geoPlotPlan(countries);
    plan.plotted.forEach(({ ct, coords }) => {
      const comps = geo.compsInCountry(ct);
      const rivals = comps.filter((c) => !c.isBf);
      /* The client's footprint is keyed by its COMPANY ID, not by its display short
         name. Looking it up as data.geoData["KSSL"] worked only while the archive
         wrote uppercase codes; the pipeline writes slugs, so the UAE pin listed a
         sourced KSSL supply row under the badge "No activity on file". Find the
         client the way the rest of the map does — the company flagged isBf. */
      const clientRow = (data.geoComps || []).find((c) => c.isBf);
      const ownData =
        (data.geoData &&
          (data.geoData[clientRow?.id] || data.geoData[data.client?.short || "KSSL"])) ||
        {};
      const isKoelPresent = !!ownData[ct];
      const isSelected = selectedCountry === ct;

      const clientLabel = (data.client && (data.client.short || data.client.name)) || "KSSL";
      /* "Contested" requires an actual rival presence row here — a country with no
         activity on file is reported as exactly that, not as a contested market.

         The wording is built in lib/geoBadge.js, as data, so it can be asserted without
         a map. Two faults live in there rather than here: the badge used to append the
         LABELS of the client's own rows, and actLabel.bf is "KSSL present", so India
         rendered "KSSL Present · KSSL present / Local production"; and it never read
         src, so an analytical estimate (the client's Saudi Arabia and Europe rows are
         both src='syn') drew exactly like a sourced presence. */
      const badge = presenceBadge({
        clientLabel,
        rows: ownData[ct] || [],
        rivalCount: rivals.length,
        actLabel: data.actLabel,
      });
      /* A presence that rests only on estimates is drawn hollow, not solid green. The
         tooltip alone would not do: a reader scanning the map sees dots, and a dot is
         the assertion. Same rule as the badge's wording, same input (row.src). */
      const estimateOnly = badge.cls.includes("est");
      const color = isKoelPresent ? "#3fa86a" : rivals.length > 0 ? "#f0593c" : "#e0a020";
      const radius = isSelected ? 11 : isKoelPresent ? 8 : 6;

      let compRowsHtml = "";
      comps.slice(0, 5).forEach((c) => {
        // Trade lines render only when a real entry exists — no fabricated fallback.
        const matInfo = COMPANY_MATERIALS[c.name];
        /* What the company DOES here, read from this country's own rows. The label
           used to be `isBf ? "KSSL HQ / Direct" : "Competitor"`, and isBf means "this
           company is the client" — not "this country is its head office" — so every
           pin the client appeared on was captioned as its HQ, the UAE included.

           The head-office test used to be a raw full-string equality between geo_comp.hq
           and the country name. The archived reference rows store a bare "Germany" and
           matched; every pipeline row stores a chain ("Ahmedabad, Gujarat, India") and
           never could, so the badge had silently stopped firing for the whole live
           roster. isHeadOffice asks the stated origin column first and falls back to the
           tidied hq — one rule, shared with the Profile page. */
        const rowsHere = (data.geoData && data.geoData[c.id] && data.geoData[c.id][ct]) || [];
        const role = companyRole({
          comp: c,
          rows: rowsHere,
          actLabel: data.actLabel,
          clientLabel,
          isHq: isHeadOffice(ct, { origin: companyOrigin(data, c.id), hq: c.hq }),
        });
        compRowsHtml += `
          <div class="gm-comp-row">
            <div class="gm-comp-head">
              <span class="gm-comp-name">${c.name}</span>
              <span class="gm-comp-role">${role}</span>
            </div>
            ${matInfo ? `<div class="gm-mat-line"><b>Exports:</b> ${matInfo.exports}</div>
            <div class="gm-mat-line"><b>Imports:</b> ${matInfo.imports}</div>` : ""}
          </div>
        `;
      });

      const tooltipContent = `
        <div class="gm-tooltip">
          <div class="gm-header">
            <span class="gm-country-name">${ct}</span>
            <span class="gm-koel-badge ${badge.cls}">${badge.text}</span>
          </div>
          ${badge.note ? `<div class="gm-evidence-note">${badge.note}</div>` : ""}
          <div class="gm-section-title">Active Companies & Material Trade</div>
          <div class="gm-comp-list">
            ${compRowsHtml}
          </div>
          <div class="gm-click-hint">Click point to open market product details ↗</div>
        </div>
      `;

      // Plot single marker on static map
      const marker = L.circleMarker(coords, {
        radius,
        fillColor: color,
        color: isSelected ? "#ffffff" : color,
        weight: isSelected ? 3 : 1.5,
        opacity: 0.95,
        // hollow + dashed where the presence is an estimate; solid where it is sourced
        fillOpacity: estimateOnly ? 0.12 : 0.85,
        dashArray: estimateOnly ? "3 3" : null,
      }).addTo(map);

      marker.bindTooltip(tooltipContent, {
        direction: "top",
        sticky: true,
        className: "geo-leaflet-tooltip",
      });

      marker.on("click", () => {
        onSelectCountry(ct);
      });
    });

    setTimeout(() => {
      map.invalidateSize();
    }, 150);
  }, [data, geo, countries, selectedCountry, onSelectCountry]);

  return (
    <div className="geo-map-wrapper" style={{ position: "relative" }}>
      <div className="geo-map-container" ref={mapContainerRef} />
      {/* One stack, so the two notices cannot overlap each other: .geo-map-unplotted
          wraps to two lines as soon as the corpus reaches a few more regions, and a
          second absolutely-positioned bar at a fixed offset would sit on top of it. */}
      <div className="geo-map-notes">
        <GeoClientFootprint data={data} />
        <GeoUnplotted countries={countries} />
      </div>
      {!countries.length ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            pointerEvents: "none",
            zIndex: 500,
          }}
        >
          <div
            style={{
              background: "rgba(20,20,24,0.85)",
              color: "#c9c9cf",
              fontFamily: "var(--mono)",
              fontSize: "12px",
              padding: "10px 16px",
              borderRadius: "4px",
              border: "1px solid #2a2a2f",
            }}
          >
            No geographic activity on file yet — the map plots only served footprint data.
          </div>
        </div>
      ) : null}
    </div>
  );
}
