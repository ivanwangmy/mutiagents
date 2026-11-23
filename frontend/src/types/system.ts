export interface HealthResponse {
  status: string
  database: string
  model_configured: boolean
  version: string
}

export interface SystemInfo {
  app_name: string
  app_env: string
  python_version: string
  platform: string
  database_backend: string
  checkpointer_backend: string
  agent_count: number
  model_name: string
  limits: Record<string, number>
}

export interface ConfigStatus {
  model_configured: boolean
  model_name: string
  provider: string
  capabilities: Record<string, string | boolean>
  missing: string[]
}
