import { RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'

export interface PageRefreshButtonProps {
  /** Refetch the page's data (usually `queryClient.refetchQueries`). */
  onRefresh: () => void
  /** Spin the icon and disable the button while a refetch is in flight. */
  refreshing?: boolean
}

/**
 * Icon-only "refresh" control for a page header. Mirrors the transactions
 * page's refresh button so every page reads the same word and behaves the
 * same: it spins and disables while a refetch is in flight.
 */
export function PageRefreshButton({ onRefresh, refreshing = false }: PageRefreshButtonProps) {
  const { t } = useTranslation()
  const label = t('transactions.refresh')

  return (
    <Button
      variant="outline"
      size="icon"
      className="!size-9"
      aria-label={label}
      title={label}
      data-testid="page-refresh-button"
      disabled={refreshing}
      onClick={onRefresh}
    >
      <RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />
    </Button>
  )
}
