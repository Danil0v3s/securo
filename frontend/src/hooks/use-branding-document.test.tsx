import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { act, waitFor } from '@testing-library/react'

import { useBrandingDocument } from '@/hooks/use-branding-document'
import { createTestQueryClient, renderWithProviders } from '@/test/utils'

function BrandingDocumentProbe() {
  useBrandingDocument()
  return null
}

// The icon links index.html ships, each with its own file.
const SHIPPED_ICONS: Array<[string, string]> = [
  ['icon', '/favicon.ico'],
  ['icon', '/favicon-32x32.png'],
  ['icon', '/favicon-16x16.png'],
  ['icon', '/favicon-96x96.png'],
  ['apple-touch-icon', '/apple-touch-icon.png'],
]

const BRANDED = {
  features: { agents: false },
  branding: {
    name: 'Household Ledger',
    logo_url: null,
    favicon_url: '/branding/favicon.png',
  },
}

describe('useBrandingDocument (issue #1045)', () => {
  let links: HTMLLinkElement[]
  const previousTitle = document.title

  beforeEach(() => {
    links = SHIPPED_ICONS.map(([rel, href]) => {
      const link = document.createElement('link')
      link.rel = rel
      link.setAttribute('href', href)
      document.head.appendChild(link)
      return link
    })
    document.title = 'Securo'
  })

  afterEach(() => {
    links.forEach((link) => link.remove())
    document.title = previousTitle
  })

  const hrefs = () => links.map((link) => link.getAttribute('href'))
  const shipped = SHIPPED_ICONS.map(([, href]) => href)

  it('sets the tab title and every favicon link when the deployment has a brand', () => {
    const queryClient = createTestQueryClient()
    queryClient.setQueryData(['app-info'], BRANDED)

    renderWithProviders(<BrandingDocumentProbe />, { queryClient })

    expect(document.title).toBe('Household Ledger')
    expect(hrefs()).toEqual(shipped.map(() => '/branding/favicon.png'))
  })

  it('restores the shipped title and each original icon when the brand goes away', async () => {
    const queryClient = createTestQueryClient()
    queryClient.setQueryData(['app-info'], BRANDED)
    renderWithProviders(<BrandingDocumentProbe />, { queryClient })
    expect(document.title).toBe('Household Ledger')

    act(() => {
      queryClient.setQueryData(['app-info'], { features: { agents: false } })
    })

    // The query cache notifies observers on a timer, so wait for the rerender.
    await waitFor(() => expect(document.title).toBe('Securo'))
    expect(hrefs()).toEqual(shipped)
  })

  it('leaves the tab alone when /api/info has no branding block', () => {
    const queryClient = createTestQueryClient()
    queryClient.setQueryData(['app-info'], { features: { agents: false } })

    renderWithProviders(<BrandingDocumentProbe />, { queryClient })

    expect(document.title).toBe('Securo')
    expect(hrefs()).toEqual(shipped)
  })

  it('leaves the tab alone while the request is still pending', () => {
    renderWithProviders(<BrandingDocumentProbe />)

    expect(document.title).toBe('Securo')
    expect(hrefs()).toEqual(shipped)
  })
})
