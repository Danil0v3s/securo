import { useEffect } from 'react'
import { useBranding } from '@/hooks/use-branding'

const ICON_LINKS = 'link[rel="icon"], link[rel="apple-touch-icon"]'

// What index.html shipped, recorded before the first change so a brand
// that is later unset (or a failed refetch) puts the built-in tab back.
// Per link, since each icon has its own size and file.
let originalTitle: string | null = null
const originalHrefs = new WeakMap<HTMLLinkElement, string | null>()

/**
 * Applies the instance brand to the browser tab (white label, issue #1045):
 * the document title and the favicon links. With nothing configured the
 * static <title> and favicons shipped in index.html stay as they are, and
 * when a configured value goes away the originals are restored.
 */
export function useBrandingDocument() {
  const { appName, faviconUrl } = useBranding()

  useEffect(() => {
    if (originalTitle === null) originalTitle = document.title
    document.title = appName ?? originalTitle
  }, [appName])

  useEffect(() => {
    document.querySelectorAll<HTMLLinkElement>(ICON_LINKS).forEach((link) => {
      if (!originalHrefs.has(link)) originalHrefs.set(link, link.getAttribute('href'))
      const original = originalHrefs.get(link) ?? null
      if (faviconUrl) {
        link.setAttribute('href', faviconUrl)
      } else if (original !== null) {
        link.setAttribute('href', original)
      }
    })
  }, [faviconUrl])
}
