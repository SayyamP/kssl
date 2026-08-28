import { Component } from "react";

/* WHY THIS EXISTS.

   Twice in one day a single bad field in the generated dataset took the WHOLE application down to
   a blank page with an empty console:

     * `overviewConfig.tech` where the wiring reads `.technology` -- spreading `undefined` does not
       throw, so the failure surfaced far away, during render.
     * `details[id].lens` emitted as the string "SPEC RANK" where the detail panel does
       `detail.lens.length ? detail.lens.map(...)`. A string is truthy, has a length, and has no
       `.map`. Clicking any signal threw inside render.

   React 18 unmounts the entire tree when a render throws and there is no boundary above it. So a
   mistake in one card's one field costs the user every tab, every panel, and any clue about what
   happened. That is a disproportionate failure and it is the boundary's job to stop it.

   This does NOT hide the error. It prints it, keeps the rest of the application alive, and says
   plainly which part failed -- because a dashboard that silently omits a broken panel is the same
   lie as a dashboard that shows a number it cannot support. */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Keep it in the console too: the boundary is a safety net, not a reason to stop looking.
    console.error("panel failed:", this.props.label || "unknown", error, info?.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="eb-fail" role="alert" style={{ padding: "18px", fontFamily: "var(--mono)" }}>
        <div style={{ color: "var(--threat, #c8553d)", fontSize: "11px", letterSpacing: ".08em" }}>
          {(this.props.label || "THIS PANEL").toUpperCase()} COULD NOT RENDER
        </div>
        <div style={{ fontSize: "12px", marginTop: "8px", opacity: 0.8 }}>
          {String(this.state.error?.message || this.state.error)}
        </div>
        <div style={{ fontSize: "11px", marginTop: "10px", opacity: 0.55 }}>
          {this.props.root
            ? "This failure took down the whole dashboard shell — reload the page; if it persists, the fault is in the served dataset or the app chrome, not one panel."
            : "The other views are unaffected. This is a fault in the served data or rendering for this panel, not in the data behind the other panels."}
        </div>
        <button
          onClick={() => this.setState({ error: null })}
          style={{ marginTop: "12px", fontSize: "11px", cursor: "pointer" }}
          type="button"
        >
          try again
        </button>
      </div>
    );
  }
}
