export type NotificationScope = 'ROLE_MEMBERS' | 'WORKSHOP' | 'SUBMITTER'

export interface NotificationRoleOption {
  role_code: string
  display_name: string
  archived: boolean
}

export interface NotificationRule {
  event_code: string
  display_name: string
  name: string
  title_template: string
  body_template: string
  allowed_variables: string[]
  required_variables: string[]
  supported_scopes: NotificationScope[]
  scope_labels: Record<string, string>
  recipient_role_codes: string[]
  recipient_roles: NotificationRoleOption[]
  recipient_scope: NotificationScope
  enabled: boolean
  version: number
  updated_at: string | null
  updated_by: string
  etag: string
  target_key: string
  warnings?: string[]
}

export interface NotificationRulesResponse {
  data: NotificationRule[]
  roles: NotificationRoleOption[]
}

export interface NotificationRuleResponse { data: NotificationRule; etag: string }

export interface NotificationRuleWrite {
  name: string
  title_template: string
  body_template: string
  recipient_role_codes: string[]
  recipient_scope: NotificationScope
  enabled: boolean
}

export interface NotificationPreview {
  event_code: string
  title: string
  body: string
  recipient_scope: NotificationScope
  scope_label: string
  recipient_role_codes: string[]
  will_send: boolean
  recipient_note?: string
  warnings?: string[]
}

export interface NotificationTarget {
  target_key: string
  object_id: string // 真实业务UUID；任务/BOM及两类委外分别保留自身对象身份，不能混传。
  route_name: string
  params: Record<string, string>
}

export type NotificationChannelStatus = 'PENDING' | 'PROCESSING' | 'ACCEPTED' | 'FAILED' | 'UNCERTAIN' | 'SKIPPED'

export interface NotificationItem {
  id: string // 收件记录 UUID，不是事件或投递 ID。
  event_code: string
  event_name: string
  title: string
  body: string
  created_at: string
  read_at: string | null
  target: NotificationTarget | null
  target_accessible: boolean
  channel_status: Partial<Record<'IN_APP' | 'WECOM', { status: NotificationChannelStatus; error_code: string }>>
}

export interface NotificationInboxResponse {
  data: NotificationItem[]
  count: number
  page: number
  page_size: number
}
