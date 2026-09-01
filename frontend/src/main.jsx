import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/index.css";

/* On every fresh page load, start at the home overview with all tabs in their
   default (unselected) state. Per-tab selections are still remembered while you
   navigate within a session; a browser reload wipes them. */
try {
  [
    "kssl_parallax_route",
    "kssl_pos_selected",
    "kssl_geo_state",
    "kssl_innov_state",
    "kssl_part_state",
    "kssl_pat_state",
    "kssl_tender_state",
    "kssl_gap_cat",
    "kssl_market_section",
  ].forEach((k) => localStorage.removeItem(k));
  if (window.location.hash) window.history.replaceState(null, "", window.location.pathname);
} catch (e) {}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
