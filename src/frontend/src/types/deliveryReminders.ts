export type DeliveryReminderStatus = 'OVERDUE' | 'DUE_TODAY' | 'NEAR_DUE' | 'REVIEW' | 'UPCOMING'
export type DeliveryFollowUp = Exclude<DeliveryReminderStatus, 'UPCOMING'> | 'ALL' | 'FOLLOW_UP'

export interface ReminderFilters {
  follow_up: DeliveryFollowUp
  owner: string
}

export interface DeliveryReminder {
  status: DeliveryReminderStatus
  label: string
  due: string | null
  quantity: string | null
  unit: string
  action: string
  owner: string
  reference: string
  reason: string
  shared: boolean
}
