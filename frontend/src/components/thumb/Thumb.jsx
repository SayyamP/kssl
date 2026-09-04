import { useState } from "react";

/* One article image, and one honest answer when there isn't one.

   Reported: "Images for Allen Control Systems and similarly affected entries are not
   displayed. Missing images should use a defined fallback rather than a broken or
   blank area."

   Two different faults were producing the same broken box, and only one of them is
   about missing data:

     1. NO URL. Five render sites wrote `<img src={item.image} />` with no guard, so a
        card with no image became `<img src={undefined}>` -- which every browser draws
        as its broken-image glyph. Measured on production: 123 of the 1,175 served
        signal cards carry no image at all, and Allen Control Systems is one of them
        (2 cards, 1 image).
     2. THE URL DOES NOT LOAD. A publisher that blocks hotlinking, or a link that has
        rotted, fails at fetch time. No site had an onError, so a perfectly well-formed
        record also ended as a broken box.

   partners.js already drew a neutral captioned tile for case 1. It was the only place
   that did. This component is that tile, made shared, and extended to case 2.

   `FAILED` is module-level on purpose: a URL that failed once must not be requested
   again when the card scrolls back into view or the panel remounts. That is the whole
   of the caching that can be done from here -- images are third-party origins, so the
   only durable cache is the browser's own HTTP cache, which the publisher's headers
   control. Serving them from our origin would need a proxy, which is a backend change
   and is NOT done here. */
const FAILED = new Set();

/* Pure, and exported, so the rule can be tested without React or a DOM. Only http(s):
   a `data:` or `javascript:` value is not something this app publishes, and an <img>
   is a place a stray value would otherwise be honoured silently. */
export function thumbUsable(src, failed = FAILED) {
  return typeof src === "string" && /^https?:\/\//i.test(src) && !failed.has(src);
}

export function thumbMarkFailed(src, failed = FAILED) {
  if (typeof src === "string" && src) failed.add(src);
  return failed;
}

export default function Thumb({ src, alt, className, style, caption }) {
  const usable = thumbUsable(src);
  const [broken, setBroken] = useState(false);

  if (!usable || broken) {
    return (
      <div className={`thumb-none ${className || ""}`} style={style}>
        <span className="thumb-none-label">
          {caption || "No image published with this article"}
        </span>
      </div>
    );
  }
  return (
    <img
      alt={alt || ""}
      className={className}
      decoding="async"
      loading="lazy"
      onError={() => {
        thumbMarkFailed(src);
        setBroken(true);
      }}
      src={src}
      style={style}
    />
  );
}
