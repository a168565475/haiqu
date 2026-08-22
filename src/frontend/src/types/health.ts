export interface HealthResponse {
  status: 'ok' | 'error'
  service: string
  database: 'ok' | 'error'
  redis: 'ok' | 'error'
  errors?: Record<string, string>
}
