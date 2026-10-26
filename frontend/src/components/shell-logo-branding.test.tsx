import { beforeEach, describe, expect, it, vi } from 'vitest'
import { waitFor } from '@testing-library/react'

import { ShellLogo } from '@/components/shell-logo'
import { renderWithProviders } from '@/test/utils'

const info = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/lib/api', () => ({ info }))

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ShellLogo white label (issue #1045)', () => {
  it('shows the instance logo when the deployment sets one', async () => {
    info.get.mockResolvedValue({
      features: { agents: false },
      branding: {
        name: 'Household Ledger',
        logo_url: '/branding/logo.png',
        favicon_url: null,
      },
    })

    const { container } = renderWithProviders(
      <ShellLogo size={32} className="text-primary" />,
    )

    const img = await waitFor(
      () => {
        const el = container.querySelector('img')
        expect(el).not.toBeNull()
        return el as HTMLImageElement
      },
    )
    expect(img).toHaveAttribute('src', '/branding/logo.png')
    expect(img).toHaveAttribute('width', '32')
    expect(img).toHaveAttribute('height', '32')
    expect(container.querySelector('svg')).not.toBeInTheDocument()
  })
})
