import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'

import { AuthBrandPanel } from '@/components/auth-brand-panel'
import { renderWithProviders } from '@/test/utils'

const branding = vi.hoisted(() => ({
  current: {
    appName: null as string | null,
    logoUrl: null as string | null,
    faviconUrl: null as string | null,
  },
}))

vi.mock('@/hooks/use-branding', () => ({
  useBranding: () => branding.current,
}))

beforeEach(() => {
  branding.current = { appName: null, logoUrl: null, faviconUrl: null }
})

describe('AuthBrandPanel white label (issue #1045)', () => {
  it('shows the instance name when the deployment sets one', () => {
    branding.current = { appName: 'Household Ledger', logoUrl: null, faviconUrl: null }
    renderWithProviders(<AuthBrandPanel />)
    expect(screen.getByText('Household Ledger')).toBeInTheDocument()
  })

  it('dims a custom logo in the oversized watermark but not in the wordmark', () => {
    branding.current = { appName: 'Household Ledger', logoUrl: '/branding/logo.png', faviconUrl: null }
    const { container } = renderWithProviders(<AuthBrandPanel />)

    const images = Array.from(container.querySelectorAll('img'))
    const watermark = images.find((img) => img.getAttribute('width') === '640')
    const wordmark = images.find((img) => img.getAttribute('width') === '20')
    expect(watermark).toHaveClass('opacity-[0.06]')
    expect(wordmark).toBeDefined()
    expect(wordmark?.className ?? '').not.toMatch(/opacity/)
  })
})
