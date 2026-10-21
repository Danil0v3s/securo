/**
 * Cross-tab data-change signal.
 *
 * The query cache is per tab: a change made in another tab (a rule
 * re-applied to existing transactions, an edited transaction) never reaches
 * this tab's cache, so its lists keep showing the stale data until the
 * global staleTime runs out. The response interceptor in `api.ts` bumps this
 * key after every successful mutation, and the browser's `storage` event
 * (which fires in every other tab, never in the one that wrote) is what
 * `useCrossTabRefresh` listens for.
 */
export const DATA_CHANGED_KEY = 'securo.data-changed'

/**
 * Record that a mutation succeeded in this tab.
 *
 * A new value on every call so even two quick changes both notify the other
 * tabs. No-op where storage is unavailable (private mode): cross-tab refresh
 * is a convenience, and the same-tab invalidations still apply.
 */
export function markDataChanged(): void {
  try {
    localStorage.setItem(DATA_CHANGED_KEY, String(Date.now()))
  } catch {
    // Ignore: nothing to do when localStorage throws.
  }
}
