/** Unit 16: small shared formatters for the dashboard's numeric-or-null
 * KPI/exception fields — every one of them is null-able server-side
 * (NULLIF-guarded SQL, PRD Appendix A) before enough data exists. */

export function formatPercent(value: string | null): string | null {
  return value == null ? null : `${value}%`;
}

export function formatDays(value: string | null): string | null {
  return value == null ? null : `${value}d`;
}

export function formatDate(value: string): string {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function formatDateTime(value: string): string {
  return new Date(value).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** "2026-09-14" -> "Sep 14" for chart axes (UTC, so the day never shifts). */
export function formatShortDate(value: string): string {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** 12345.6 -> "$12.3k" for compact money labels. */
export function formatCompactCurrency(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatCompactNumber(value: number): string {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(
    value
  );
}
