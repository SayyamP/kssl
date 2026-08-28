export function formatNumber(value, locale = "en-IN") {
  return new Intl.NumberFormat(locale).format(Number(value || 0));
}

/* ₹ crore, the unit every exposure figure on this platform is quoted in. */
export function formatCrore(value) {
  const v = Number(value || 0);
  if (v >= 1000) return `₹${(v / 1000).toFixed(1).replace(/\.0$/, "")}k cr`;
  return v > 0 ? `₹${formatNumber(v)} cr` : "—";
}
