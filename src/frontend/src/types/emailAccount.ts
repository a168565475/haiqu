export type SmtpSecurity = 'STARTTLS' | 'SSL'
export type EmailAccountTestStatus = 'NOT_TESTED' | 'SUCCESS' | 'FAILED'

export interface EmailAccount {
  id: string
  display_name: string
  sender_name: string
  sender_email: string
  smtp_host: string
  smtp_port: number
  smtp_username: string
  smtp_security: SmtpSecurity
  is_enabled: boolean
  is_default: boolean
  password_configured: boolean
  last_test_status: EmailAccountTestStatus
  last_tested_at: string | null
  created_at: string
  updated_at: string
}

export interface EmailAccountInput {
  display_name: string
  sender_name: string
  sender_email: string
  smtp_host: string
  smtp_port: number
  smtp_username: string
  smtp_password?: string
  smtp_security: SmtpSecurity
  is_enabled: boolean
}

export interface VersionedEmailAccount {
  data: EmailAccount
  etag: string
}

