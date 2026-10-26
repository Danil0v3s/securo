import { useEffect } from 'react'
import { useBranding } from '@/hooks/use-branding'

/**
 * Applies the instance brand to the browser tab (white label, issue #1045):
 * the document title and the favicon links. Each effect is a no-op unless
 * the deployment actually set a value, so an unbranded instance keeps the
 * static <title> and favicons shipped in index.html.
 */
export function useBrandingDocument() {
  const { appName, faviconUrl } = useBranding()

  useEffect(() => {
    if (appName) {
      document.title = appName
    }
  }, [appName])

  useEffect(() => {
    if (!faviconUrl) return
    document
      .querySelectorAll<HTMLLinkElement>('link[rel="icon"], link[rel="apple-touch-icon"]')
      .forEach((link) => {
        link.href = faviconUrl
      })
  }, [faviconUrl])
}
