import { useEffect, useRef, useState } from "react";
import { srcChips } from "../../lib/html";

/* Count-up on the numeric value. The original animated by writing into the text node
   directly; here it is state, so React still owns the DOM. Non-numeric values (—, a
   date) skip the animation and render as-is.

   The tween used to count a fixed 28 requestAnimationFrame ticks. rAF is not a clock:
   the browser throttles or stops it outright when the page is not being painted, so
   the count stalled around a fifth of the way up and STAYED there — the tiles read
   15 / 4 / 4 / 1 / 0 / 1 against real values of 71 / 18 / 19 / 5 / 3 / 7, six numbers
   on screen the data never contained. It is now driven by the clock, and a timer
   independent of rAF snaps it onto the exact target no matter what the frame loop
   did. A partial value can no longer be the last thing on screen. */
const DURATION_MS = 620;

function CountUp({ text }) {
  const label = String(text);
  const target = parseFloat(label.replace(/,/g, ""));
  const hasComma = label.includes(",");
  const isNum = !Number.isNaN(target);
  const final = isNum ? (hasComma ? target.toLocaleString("en-IN") : String(target)) : label;
  const [shown, setShown] = useState(final);
  const frame = useRef(0);
  const timer = useRef(0);

  useEffect(() => {
    if (!isNum) {
      setShown(label);
      return undefined;
    }
    const reduced =
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setShown(final);
      return undefined;
    }
    let done = false;
    const settle = () => {
      if (done) return;
      done = true;
      setShown(final);
    };
    const t0 = Date.now();
    const tick = () => {
      const p = Math.min(1, (Date.now() - t0) / DURATION_MS);
      if (p >= 1) {
        settle();
        return;
      }
      const value = Math.round(target * p);
      setShown(hasComma ? value.toLocaleString("en-IN") : String(value));
      frame.current = requestAnimationFrame(tick);
    };
    setShown(hasComma ? (0).toLocaleString("en-IN") : "0");
    frame.current = requestAnimationFrame(tick);
    // the safety net: timers still fire where rAF is throttled or suspended
    timer.current = setTimeout(settle, DURATION_MS + 80);
    return () => {
      cancelAnimationFrame(frame.current);
      clearTimeout(timer.current);
      // a cancelled tween must never leave its partial value behind
      settle();
    };
  }, [target, hasComma, label, isNum, final]);

  return <>{shown}</>;
}

/* Each tile is a door into the feed — except where `inert` is set. The Market overview
   is a tender report with its own tabs and filter, so its tiles have no feed to open;
   they render as a readout with no button role, no focus stop and no "→" affordance,
   because a control that looks live and does nothing is worse than a plain number. */
export default function MetricsStrip({ metrics, active, onPick, inert = false }) {
  return (
    <div className="metrics" id="metrics">
      {metrics.map((m) => (
        <div
          className={`metric${active === m.act ? " on" : ""}${inert ? " inert" : ""}`}
          key={`${m.act}-${m.l}`}
          onClick={inert ? undefined : () => onPick(m, m.act)}
          role={inert ? undefined : "button"}
          tabIndex={inert ? undefined : 0}
          onKeyDown={
            inert
              ? undefined
              : (e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onPick(m, m.act);
                  }
                }
          }
        >
          <span className="ml">
            {m.dot ? <span className="d" style={{ background: m.dot }} /> : null}
            {m.l}
          </span>
          <span className="mv">
            <CountUp text={m.v} />
            {m.unit ? <span className="unit">{m.unit}</span> : null}
            {m.delta ? <span className="delta up">{m.delta}</span> : null}
          </span>
          <span className="msub">
            {m.sub}{" "}
            <span
              dangerouslySetInnerHTML={{
                __html: srcChips(m.src ? [{ label: "source", url: m.src }] : null, "nofilter"),
              }}
            />{" "}
            {inert ? null : <i className="arr">→</i>}
          </span>
        </div>
      ))}
    </div>
  );
}
