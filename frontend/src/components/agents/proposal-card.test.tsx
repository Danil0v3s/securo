import { screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '@/test/utils'
import { isProposalData } from '@/lib/agent-proposals'

const { linkTransfer, unlinkTransfer } = vi.hoisted(() => ({
  linkTransfer: vi.fn(),
  unlinkTransfer: vi.fn(),
}))
vi.mock('@/lib/api', () => ({
  budgets: {},
  categories: {},
  goals: {},
  recurring: {},
  rules: {},
  transactions: { linkTransfer, unlinkTransfer },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import { ProposalCard } from './proposal-card'

const debitLeg = {
  id: 'tx-debit',
  description: 'Move to savings',
  date: '2026-10-01',
  amount: 250,
  currency: 'USD',
  type: 'debit',
  account_name: 'Checking',
}
const creditLeg = {
  id: 'tx-credit',
  description: 'From checking',
  date: '2026-10-02',
  amount: 250,
  currency: 'USD',
  type: 'credit',
  account_name: 'Savings',
}

describe('ProposalCard transfer kinds', () => {
  beforeEach(() => {
    localStorage.clear()
    linkTransfer.mockReset()
    unlinkTransfer.mockReset()
  })

  it('treats the transfer tool previews as proposals', () => {
    expect(isProposalData({ kind: 'link_transfer' })).toBe(true)
    expect(isProposalData({ kind: 'unlink_transfer' })).toBe(true)
  })

  it('shows both legs of a link preview and links them on Apply', async () => {
    linkTransfer.mockResolvedValue({ transfer_pair_id: 'pair-1' })
    const { user } = renderWithProviders(
      <ProposalCard
        toolCallId="call-link"
        data={{
          kind: 'link_transfer',
          // Credit listed first: the card still reads from the debit side.
          transaction_ids: ['tx-credit', 'tx-debit'],
          legs: [creditLeg, debitLeg],
        }}
      />,
    )

    expect(screen.getByText('Link as transfer')).toBeInTheDocument()
    const summary = screen.getByText(/Checking .*→ Savings/)
    expect(summary.textContent).toContain('(2026-10-01)')

    await user.click(screen.getByRole('button', { name: /Apply/ }))

    await waitFor(() => expect(linkTransfer).toHaveBeenCalledWith(['tx-credit', 'tx-debit']))
  })

  it('unlinks the pair by its id on Apply', async () => {
    unlinkTransfer.mockResolvedValue(undefined)
    const { user } = renderWithProviders(
      <ProposalCard
        toolCallId="call-unlink"
        data={{
          kind: 'unlink_transfer',
          transfer_pair_id: 'pair-9',
          legs: [debitLeg, creditLeg],
        }}
      />,
    )

    expect(screen.getByText('Unlink transfer')).toBeInTheDocument()
    expect(screen.getByText(/go back to regular transactions/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Apply/ }))

    await waitFor(() => expect(unlinkTransfer).toHaveBeenCalledWith('pair-9'))
  })
})
