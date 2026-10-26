import { useQuery } from '@tanstack/react-query'
import { info } from '@/lib/api'

export interface Branding {
  /** Instance name (APP_NAME), or null when the deployment set none. */
  appName: string | null
  /** Custom logo URL (BRAND_LOGO_URL), or null for the built-in mark. */
  logoUrl: string | null
  /** Custom favicon URL (BRAND_FAVICON_URL), or null for the built-in one. */
  faviconUrl: string | null
}

/**
 * White label (issue #1045): the brand the deployment configured for this
 * instance, read from the same public /api/info request that feeds the
 * feature flags, so the two share one cache entry and one network call.
 * Every field is null when the deployment left the built-in brand alone.
 */
export function useBranding(): Branding {
  const { data } = useQuery({
    queryKey: ['app-info'],
    queryFn: () => info.get(),
    staleTime: 1000 * 60 * 60,
  })
  const branding = data?.branding
  return {
    appName: branding?.name ?? null,
    logoUrl: branding?.logo_url ?? null,
    faviconUrl: branding?.favicon_url ?? null,
  }
}
