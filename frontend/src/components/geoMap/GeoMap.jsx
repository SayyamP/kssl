import { useEffect, useMemo, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

/* WHERE A COUNTRY IS -- looked up, never guessed.

   This table used to have a fallback that hashed the country name into a lat/lng:
     lat = 10 + (abs(hash % 50) - 25); lng = 20 + (abs((hash >> 3) % 120) - 60)
   Sixteen of the fifty-two countries the pipeline serves missed the table and were
   drawn at those made-up coordinates -- a band covering the Atlantic and Africa, so
   Russia, Norway, Finland and Taiwan appeared in the Gulf of Guinea. The hash also
   hid the staleness it caused: a country the table did not know still produced a
   confident-looking dot, so nobody ever learned the table needed extending.

   There is no fallback now. A country with no entry is NOT drawn; it is counted and
   named on the map instead (see geoPlotPlan). Add coordinates here when the corpus
   reaches somewhere new -- the notice tells you when that has happened. */
const COUNTRY_COORDS = {
  Afghanistan: [33.9391, 67.7100],
  Argentina: [-38.4161, -63.6167],
  Armenia: [40.0691, 45.0382],
  Australia: [-25.2744, 133.7751],
  Austria: [47.5162, 14.5501],
  Bahrain: [26.0667, 50.5577],
  Bangladesh: [23.6850, 90.3563],
  Belgium: [50.5039, 4.4699],
  Brazil: [-14.2350, -51.9253],
  Canada: [56.1304, -106.3468],
  China: [35.8617, 104.1954],
  Czechia: [49.8175, 15.4730],
  "Czech Republic": [49.8175, 15.4730],
  Denmark: [56.2639, 9.5018],
  Egypt: [26.8206, 30.8025],
  Estonia: [58.5953, 25.0136],
  Ethiopia: [9.1450, 40.4897],
  Finland: [61.9241, 25.7482],
  France: [46.2276, 2.2137],
  Germany: [51.1657, 10.4515],
  Ghana: [7.9465, -1.0232],
  Greece: [39.0742, 21.8243],
  Hungary: [47.1625, 19.5033],
  India: [20.5937, 78.9629],
  Indonesia: [-0.7893, 113.9213],
  Iraq: [33.2232, 43.6793],
  Israel: [31.0461, 34.8516],
  Italy: [41.8719, 12.5674],
  Japan: [36.2048, 138.2529],
  Kazakhstan: [48.0196, 66.9237],
  Kenya: [-1.2921, 36.8219],
  Korea: [35.9078, 127.7669],
  "South Korea": [35.9078, 127.7669],
  "Republic of Korea": [35.9078, 127.7669],
  KSA: [23.8859, 45.0792],
  Kuwait: [29.3117, 47.4818],
  Malaysia: [4.2105, 101.9758],
  Mexico: [23.6345, -102.5528],
  Morocco: [31.7917, -7.0926],
  Netherlands: [52.1326, 5.2913],
  "The Netherlands": [52.1326, 5.2913],
  "New Zealand": [-40.9006, 174.8860],
  Nigeria: [9.0820, 8.6753],
  Norway: [60.4720, 8.4689],
  Oman: [21.5126, 55.9233],
  Pakistan: [30.3753, 69.3451],
  Philippines: [12.8797, 121.7740],
  Poland: [51.9194, 19.1451],
  Qatar: [25.3548, 51.1839],
  Romania: [45.9432, 24.9668],
  Russia: [61.5240, 105.3188],
  "Russian Federation": [61.5240, 105.3188],
  "Saudi Arabia": [23.8859, 45.0792],
  Singapore: [1.3521, 103.8198],
  "South Africa": [-30.5595, 22.9375],
  Spain: [40.4637, -3.7492],
  "Sri Lanka": [7.8731, 80.7718],
  Sweden: [60.1282, 18.6435],
  Taiwan: [23.6978, 120.9605],
  Tanzania: [-6.3690, 34.8888],
  Thailand: [15.8700, 100.9925],
  Turkey: [38.9637, 35.2433],
  Uganda: [1.3733, 32.2903],
  UAE: [23.4241, 53.8478],
  "United Arab Emirates": [23.4241, 53.8478],
  UK: [55.3781, -3.4360],
  "United Kingdom": [55.3781, -3.4360],
  Ukraine: [48.3794, 31.1656],
  USA: [37.0902, -95.7129],
  "United States": [37.0902, -95.7129],
  "United States of America": [37.0902, -95.7129],
  Vietnam: [14.0583, 108.2772],
  Algeria: [28.0339, 1.6596],
  Azerbaijan: [40.1431, 47.5769],
  Bulgaria: [42.7339, 25.4858],
  Chile: [-35.6751, -71.5430],
  Colombia: [4.5709, -74.2973],
  Croatia: [45.1000, 15.2000],
  Ireland: [53.4129, -8.2439],
  Jordan: [30.5852, 36.2384],
  Latvia: [56.8796, 24.6032],
  Lithuania: [55.1694, 23.8813],
  Slovakia: [48.6690, 19.6990],
  Slovenia: [46.1512, 14.9955],
  Switzerland: [46.8182, 8.2275],
};

/* Not countries. The footprint table carries continent-level rows, and a continent
   has no honest point: "Europe" was pinned at 54.5N 15.2E, which is inside Poland --
   a country that is separately its own row, so one place got two dots and the reader
   had no way to tell which was which. These are reported beside the map instead. */
const REGION_ROWS = new Set(["Africa", "Europe", "Asia", "Middle East",
  "Latin America", "South America", "North America", "Global", "Worldwide"]);

export function geoCountryCoords(countryName) {
  if (!countryName) return null;
  if (COUNTRY_COORDS[countryName]) return COUNTRY_COORDS[countryName];
  const hit = Object.keys(COUNTRY_COORDS).find(
    (k) => k.toLowerCase() === String(countryName).toLowerCase(),
  );
  return hit ? COUNTRY_COORDS[hit] : null;
}

/* Split the served countries into what can be drawn and what cannot.

   Pure, and exported, so the rule can be tested without a map: the old fallback was
   unreachable from any test because it lived inside a Leaflet render effect. */
export function geoPlotPlan(countries) {
  const plotted = [];
  const regions = [];
  const unlocated = [];
  (countries || []).forEach((ct) => {
    if (REGION_ROWS.has(ct)) {
      regions.push(ct);
      return;
    }
    const coords = geoCountryCoords(ct);
    if (coords) plotted.push({ ct, coords });
    else unlocated.push(ct);
  });
  return { plotted, regions, unlocated };
}

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

      const color = isKoelPresent ? "#3fa86a" : rivals.length > 0 ? "#f0593c" : "#e0a020";
      const radius = isSelected ? 11 : isKoelPresent ? 8 : 6;

      const clientLabel = (data.client && (data.client.short || data.client.name)) || "KSSL";
      /* "Contested" requires an actual rival presence row here — a country with no
         activity on file is reported as exactly that, not as a contested market. */
      /* Name the activity actually on file. "Direct / Export / Assembly" was printed
         for every country the client appeared in, which asserts two modes we may
         have no row for -- the same fault as captioning the UAE pin as an HQ. */
      const ownActs = [
        ...new Set((ownData[ct] || []).map((r) => (data.actLabel || {})[r.c]).filter(Boolean)),
      ];
      const koelStatusText = isKoelPresent
        ? `${clientLabel} Present${ownActs.length ? ` · ${ownActs.join(" / ")}` : ""}`
        : rivals.length > 0
          ? `${clientLabel} Absent · Contested Market ⚠`
          : "No activity on file";

      let compRowsHtml = "";
      comps.slice(0, 5).forEach((c) => {
        // Trade lines render only when a real entry exists — no fabricated fallback.
        const matInfo = COMPANY_MATERIALS[c.name];
        /* What the company DOES here, read from this country's own rows. The label
           used to be `isBf ? "KSSL HQ / Direct" : "Competitor"`, and isBf means "this
           company is the client" — not "this country is its head office" — so every
           pin the client appeared on was captioned as its HQ, the UAE included. */
        const rowsHere = (data.geoData && data.geoData[c.id] && data.geoData[c.id][ct]) || [];
        const acts = [
          ...new Set(rowsHere.map((r) => (data.actLabel || {})[r.c]).filter(Boolean)),
        ];
        const isHq = !!c.hq && String(c.hq).toLowerCase() === String(ct).toLowerCase();
        const roleParts = isHq ? ["Head office", ...acts] : acts;
        const role = roleParts.length
          ? roleParts.join(" · ")
          : c.isBf
            ? `${clientLabel} presence`
            : "Competitor";
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
            <span class="gm-koel-badge ${isKoelPresent ? "present" : "absent"}">${koelStatusText}</span>
          </div>
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
        fillOpacity: 0.85,
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
      <GeoUnplotted countries={countries} />
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
