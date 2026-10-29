/**
 * Month navigation helpers shared by the dashboard and the transactions page.
 *
 * Months are represented as `"YYYY-MM"` strings. Day ranges are emitted as
 * `"YYYY-MM-DD"` strings WITHOUT a time component, matching the date-range
 * filter and the `?from`/`?to` URL params (which are timezone-naive).
 */

/** Current month as `"YYYY-MM"` (browser local time). */
export function currentMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

/** Shift a `"YYYY-MM"` month by `delta` months (handles year overflow). */
export function shiftMonth(yearMonth: string, delta: number): string {
  const [y, m] = yearMonth.split('-').map(Number)
  const d = new Date(y, m - 1 + delta, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

/** Last day-of-month number for a `"YYYY-MM"` month (28–31, leap-year aware). */
export function monthLastDay(yearMonth: string): number {
  const [y, m] = yearMonth.split('-').map(Number)
  return new Date(y, m, 0).getDate()
}

/** First/last day of a `"YYYY-MM"` month as `"YYYY-MM-DD"` strings. */
export function monthRange(yearMonth: string): { from: string; to: string } {
  return {
    from: `${yearMonth}-01`,
    to: `${yearMonth}-${String(monthLastDay(yearMonth)).padStart(2, '0')}`,
  }
}

/**
 * Day range for a reporting period. Without a pay-cycle day this is the
 * calendar month (delegates to `monthRange`). With a cycle start day D, the
 * period labeled by month M runs from day D of the previous month through day
 * D-1 of month M (payday→payday), mirroring the backend `_period_range`.
 * `to` is inclusive, like `monthRange`.
 */
export function periodRange(yearMonth: string, cycleStartDay?: number | null): { from: string; to: string } {
  if (!cycleStartDay) return monthRange(yearMonth)
  const [y, m] = yearMonth.split('-').map(Number)
  const pad = (n: number) => String(n).padStart(2, '0')
  const fmt = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  const start = new Date(y, m - 2, cycleStartDay) // day D of month M-1
  const endIncl = new Date(y, m - 1, cycleStartDay - 1) // day D-1 of month M (inclusive)
  return { from: fmt(start), to: fmt(endIncl) }
}

/** Localized label for a `"YYYY-MM"` month, e.g. "Maio de 2026" / "May 2026". */
export function monthLabel(yearMonth: string, locale = 'pt-BR'): string {
  const [y, m] = yearMonth.split('-').map(Number)
  return new Date(y, m - 1, 2).toLocaleDateString(locale, { month: 'long', year: 'numeric' })
}

/**
 * If a `from`/`to` pair exactly spans one full calendar month, return that
 * month as `"YYYY-MM"`. Otherwise return null (custom range / no filter).
 * Lets the stepper reflect the active date-range filter as a single month.
 */
export function monthFromRange(from: string | null | undefined, to: string | null | undefined): string | null {
  if (!from || !to) return null
  const ym = from.slice(0, 7)
  const expected = monthRange(ym)
  return from === expected.from && to === expected.to ? ym : null
}
