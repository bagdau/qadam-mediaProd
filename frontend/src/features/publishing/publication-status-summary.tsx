import type { PublicationStatus } from '@/types/api'
import { PUBLICATION_STATUS } from '@/utils/status'

export function PublicationStatusSummary({ status }: { status: PublicationStatus }) {
  const item = PUBLICATION_STATUS[status]
  return <div aria-label={`Статус: ${item.label}`}><strong>{item.label}</strong><p>{item.description}</p></div>
}
