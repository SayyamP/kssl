/**
 * Tender Deadline Calculation Helper.
 * Checks DB record for tender closing dates / dl offset, and calculates
 * real days left dynamically relative to current system date.
 */

export function computeTenderRealDays(tender, referenceDate = new Date()) {
  if (!tender) {
    return {
      dl: 0,
      deadline: "—",
      timing: "—",
      status: "closed",
      class: "settled",
      isLive: false,
    };
  }

  const rawStatus = (tender.status || "").toLowerCase();
  const isAwardedOrSettled =
    rawStatus === "awarded" ||
    rawStatus === "settled" ||
    (tender.deadline && tender.deadline.toLowerCase().startsWith("awarded"));

  if (isAwardedOrSettled) {
    return {
      dl: 0,
      deadline: tender.deadline || "Awarded / Settled",
      timing: "Awarded — programme concluded",
      status: "awarded",
      class: "settled",
      isLive: false,
    };
  }

  /* A real programme with a published STAGE (AoN cleared, RFI, FMS approved…)
     shows the stage, not a manufactured countdown. Far dl keeps it sorted after
     anything with a genuine closing date and out of the urgency bands. */
  if (tender.stage) {
    return {
      dl: 365,
      deadline: tender.stage,
      timing: tender.stage,
      status: "open",
      class: "normal",
      isLive: true,
    };
  }

  const now = new Date(referenceDate);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

  let targetDate = null;
  let closingStr = tender.closingDate || tender.dueDate || tender.closing_date;

  if (!closingStr && Array.isArray(tender.req)) {
    const pair = tender.req.find(
      (r) =>
        r &&
        r[0] &&
        (r[0].toLowerCase().includes("closing date") ||
          r[0].toLowerCase().includes("due date") ||
          r[0].toLowerCase().includes("deadline"))
    );
    if (pair && pair[1]) closingStr = pair[1];
  }

  if (!closingStr && typeof tender.deadline === "string") {
    const m = tender.deadline.match(/(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})/);
    if (m) closingStr = m[1];
  }

  if (closingStr) {
    const parsed = new Date(closingStr);
    if (!isNaN(parsed.getTime())) {
      targetDate = parsed;
    }
  }

  /* A stored dl offset is only meaningful relative to the date the record was
     created. With no createdAt there is nothing to anchor it to — manufacturing a
     countdown from an invented anchor date is exactly the lie this module exists
     to prevent, so the record falls through to "no deadline on record" below. */
  if (
    !targetDate &&
    tender.createdAt &&
    typeof tender.dl === "number" &&
    tender.dl > 0 &&
    tender.dl < 1000
  ) {
    const baseDate = new Date(tender.createdAt);
    if (!isNaN(baseDate.getTime()))
      targetDate = new Date(baseDate.getTime() + tender.dl * 86400 * 1000);
  }

  if (targetDate && !isNaN(targetDate.getTime())) {
    const targetDay = new Date(
      targetDate.getFullYear(),
      targetDate.getMonth(),
      targetDate.getDate()
    );
    const diffMs = targetDay.getTime() - today.getTime();
    const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays <= 0) {
      return {
        dl: 0,
        deadline: "Closed / Expired",
        timing: "Closed — deadline passed",
        status: "closed",
        class: "settled",
        isLive: false,
      };
    }

    const cls = diffDays <= 7 ? "urgent" : diffDays <= 14 ? "soon" : "normal";
    return {
      dl: diffDays,
      deadline: `${diffDays} day${diffDays !== 1 ? "s" : ""} left`,
      timing: `closes in ${diffDays} day${diffDays !== 1 ? "s" : ""}`,
      status: diffDays <= 3 ? "closing" : "open",
      class: cls,
      isLive: true,
    };
  }

  /* No createdAt and no resolvable date. Only an explicit "Closed" from the
     source is treated as closed; otherwise this is an open tender whose deadline
     the record simply does not carry — say so instead of computing days from
     nothing. dl=9999 keeps it in the open bucket (dl<=0 reads as closed) and
     sorts it after everything with a genuine closing date. */
  if (tender.deadline && /closed|expired/i.test(tender.deadline)) {
    return {
      dl: 0,
      deadline: tender.deadline,
      timing: "Closed",
      status: "closed",
      class: "settled",
      isLive: false,
    };
  }
  /* A served descriptive deadline ("Q4 2026 expected") still shows — but a baked
     countdown string ("12 days left") is a stale computation, not a record, and
     repeating it would manufacture the very countdown this path refuses. */
  const desc =
    tender.deadline && !/days?\s+left|closes in/i.test(tender.deadline) ? tender.deadline : null;
  return {
    dl: 9999,
    deadline: desc || "no deadline on record",
    timing: desc || "no deadline on record",
    status: "open",
    class: "normal",
    isLive: true,
  };
}

/**
 * Wire tender dataset with calculated real days left relative to current date.
 */
export function wireTendersWithRealDays(tenders, referenceDate = new Date()) {
  if (!Array.isArray(tenders)) return [];
  return tenders.map((t) => {
    const calc = computeTenderRealDays(t, referenceDate);
    return {
      ...t,
      dl: calc.dl,
      /* The served date, kept. `deadline` is overwritten below with a countdown, so
         after wiring there was NO date left on the object -- and the columns headed
         "Closes" and "Closing date" printed "19 days left" or "no deadline on record"
         instead of a date. A countdown is a useful chip; it is not a closing date. */
      closingDate: t.deadline || null,
      deadline: calc.deadline,
      /* The whole phrase, built once here. Every call site used to write
         `closes in ${deadline}`, which read "closes in Awarded" on the 15
         concluded programmes — a countdown on a contract already signed, the
         same defect as the Feb-2023 tender that showed "6 days left". */
      timing: calc.timing,
      statusClass: calc.class,
      isLive: calc.isLive,
    };
  });
}
