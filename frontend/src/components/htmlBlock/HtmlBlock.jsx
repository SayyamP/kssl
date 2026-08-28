import { useEffect, useRef } from "react";

/* Renders a markup string produced by one of the src/lib builders.

   Why a string at all: several panels are dense, read-only briefings assembled from
   data that itself carries markup (`verdict`, `impact`, `insight` all hold <b> tags).
   Rebuilding those as JSX would mean parsing the data's own HTML anyway, so the
   builders stay string-returning and this component is the single place that injects
   them — one audited `dangerouslySetInnerHTML` instead of thirty.

   Interaction is delegated: `handlers` maps a CSS selector to a callback that gets
   (element, event). Nothing inside the string needs a global function to call, which
   is what the standalone file's inline `onclick=` attributes depended on. */
export default function HtmlBlock({ html, handlers, className, id, style, onMount }) {
  const ref = useRef(null);
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    const onClick = (event) => {
      const map = handlersRef.current;
      if (!map) return;
      for (const selector of Object.keys(map)) {
        const hit = event.target.closest(selector);
        if (hit && node.contains(hit)) {
          map[selector](hit, event);
          return;
        }
      }
    };
    const onKeyDown = (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const map = handlersRef.current;
      if (!map) return;
      for (const selector of Object.keys(map)) {
        const hit = event.target.closest(selector);
        if (hit && node.contains(hit) && hit.getAttribute("tabindex") !== null) {
          event.preventDefault();
          map[selector](hit, event);
          return;
        }
      }
    };
    node.addEventListener("click", onClick);
    node.addEventListener("keydown", onKeyDown);
    return () => {
      node.removeEventListener("click", onClick);
      node.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  useEffect(() => {
    if (onMount && ref.current) onMount(ref.current);
  }, [html, onMount]);

  return (
    <div
      className={className}
      id={id}
      ref={ref}
      style={style}
      dangerouslySetInnerHTML={{ __html: html || "" }}
    />
  );
}
