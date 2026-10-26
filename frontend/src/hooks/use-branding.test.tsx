import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { useBranding } from '@/hooks/use-branding'
import { createTestQueryClient } from '@/test/utils'

const info = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/lib/api', () => ({ info }))

let queryClient: QueryClient

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

// Asserting the fallback before the request settles would pass even with a
// broken mapping, so each fallback case waits for the query to finish.
async function settled(status: 'success' | 'error') {
  await waitFor(() =>
    expect(queryClient.getQueryState(['app-info'])?.status).toBe(status),
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  queryClient = createTestQueryClient()
})

describe('useBranding', () => {
  it('exposes the instance brand when the server sends it', async () => {
    info.get.mockResolvedValue({
      features: { agents: true },
      branding: {
        name: 'Household Ledger',
        logo_url: '/branding/logo.png',
        favicon_url: '/branding/favicon.png',
      },
    })

    const { result } = renderHook(() => useBranding(), { wrapper })

    await waitFor(() =>
      expect(result.current.appName).not.toBeNull(),
    )
    expect(result.current.appName).toBe('Household Ledger')
    expect(result.current.logoUrl).toBe('/branding/logo.png')
    expect(result.current.faviconUrl).toBe('/branding/favicon.png')
  })

  it('is all nulls when /api/info omits the branding block', async () => {
    // An older backend behind a newer frontend.
    info.get.mockResolvedValue({ features: { agents: false } })

    const { result } = renderHook(() => useBranding(), { wrapper })

    await settled('success')
    expect(result.current).toEqual({
      appName: null,
      logoUrl: null,
      faviconUrl: null,
    })
  })

  it('is all nulls when the request fails', async () => {
    info.get.mockRejectedValue(new Error('offline'))

    const { result } = renderHook(() => useBranding(), { wrapper })

    await settled('error')
    expect(result.current).toEqual({
      appName: null,
      logoUrl: null,
      faviconUrl: null,
    })
  })
})
