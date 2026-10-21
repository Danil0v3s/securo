/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DATA_CHANGED_KEY, markDataChanged } from '@/lib/data-changed'

describe('markDataChanged', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('writes the current time under the signal key', () => {
    vi.spyOn(Date, 'now').mockReturnValue(42)
    markDataChanged()
    expect(localStorage.getItem(DATA_CHANGED_KEY)).toBe('42')
  })

  it('writes a new value on each call so back-to-back changes both notify', () => {
    const now = vi.spyOn(Date, 'now').mockReturnValue(1)
    markDataChanged()
    now.mockReturnValue(2)
    markDataChanged()
    expect(localStorage.getItem(DATA_CHANGED_KEY)).toBe('2')
  })
})
