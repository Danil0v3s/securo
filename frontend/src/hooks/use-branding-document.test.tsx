import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { useBrandingDocument } from '@/hooks/use-branding-document'
import { createTestQueryClient, renderWithProviders } from '@/test/utils'

function BrandingDocumentProbe() {
  useBrandingDocument()
  return null
}

describe('useBrandingDocument (issue #1045)', () => {
  let iconLink: HTMLLinkElement
  const previousTitle = document.title

  beforeEach(() => {
    iconLink = document.createElement('link')
    iconLink.rel = 'icon'
    iconLink.href = '/favicon.svg'
    document.head.appendChild(iconLink)
    document.title = 'Securo'
  })

  afterEach(() => {
    iconLink.remove()
    document.title = previousTitle
  })

  it('sets the tab title and favicon when the deployment has a brand', () => {
    const queryClient = createTestQueryClient()
    queryClient.setQueryData(['app-info'], {
      features: { agents: false },
      branding: {
        name: 'Household Ledger',
        logo_url: null,
        favicon_url: '/branding/favicon.png',
      },
    })

    renderWithProviders(<BrandingDocumentProbe />, { queryClient })

    expect(document.title).toBe('Household Ledger')
    expect(iconLink.getAttribute('href')).toBe('/branding/favicon.png')
  })

  it('leaves the tab alone when /api/info has no branding block', () => {
    const queryClient = createTestQueryClient()
    queryClient.setQueryData(['app-info'], { features: { agents: false } })

    renderWithProviders(<BrandingDocumentProbe />, { queryClient })

    expect(document.title).toBe('Securo')
    expect(iconLink.getAttribute('href')).toBe('/favicon.svg')
  })

  it('leaves the tab alone while the request is still pending', () => {
    renderWithProviders(<BrandingDocumentProbe />)

    expect(document.title).toBe('Securo')
    expect(iconLink.getAttribute('href')).toBe('/favicon.svg')
  })
})
