import type {
  AgentExperience,
  AgentSummary,
  ChatMessage,
  ConversationDetail,
  ConversationSummary,
  ExperienceList,
  FeedbackResult,
  SendMessageResult,
  TaskState,
  TaskUsage,
  ToolCallRecord,
} from '../types/classroom'
import type { ConfigStatus, HealthResponse, SystemInfo } from '../types/system'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

function detailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object' && 'detail' in detail) {
    const inner = (detail as { detail: unknown }).detail
    if (typeof inner === 'string' && inner.trim()) return inner
    if (Array.isArray(inner) && inner.length > 0) {
      const first = inner[0] as { msg?: string }
      if (first?.msg) return first.msg
    }
  }
  return fallback
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    let detail: unknown = null
    try {
      detail = await response.json()
    } catch {
      detail = await response.text()
    }
    throw new ApiError(
      response.status,
      detailMessage(detail, `请求失败：${response.status}`),
      detail,
    )
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export const api = {
  health: () => request<HealthResponse>('/api/health'),
  systemInfo: () => request<SystemInfo>('/api/system/info'),
  configStatus: () => request<ConfigStatus>('/api/system/config-status'),

  listAgents: () => request<AgentSummary[]>('/api/agents'),

  listExperiences: (agentId: string, status?: string) => {
    const params = new URLSearchParams()
    if (status) params.set('status', status)
    const query = params.toString()
    return request<ExperienceList>(
      `/api/agents/${agentId}/experiences${query ? `?${query}` : ''}`,
    )
  },
  relevantExperiences: (agentId: string, query: string) =>
    request<{ agent_id: string; query: string; experiences: AgentExperience[] }>(
      `/api/agents/${agentId}/experiences/relevant?query=${encodeURIComponent(query)}`,
    ),
  reviewExperience: (
    agentId: string,
    experienceId: string,
    validation_status: 'candidate' | 'validated' | 'rejected',
    note?: string,
  ) =>
    request<AgentExperience>(`/api/agents/${agentId}/experiences/${experienceId}`, {
      method: 'PATCH',
      body: JSON.stringify({ validation_status, note }),
    }),
  submitFeedback: (
    conversationId: string,
    payload: { message_id?: string; agent_id?: string; rating: number; comment?: string },
  ) =>
    request<FeedbackResult>(`/api/conversations/${conversationId}/feedback`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  listConversations: () => request<ConversationSummary[]>('/api/conversations'),
  createConversation: (payload: { title?: string; selected_agent_ids: string[] }) =>
    request<ConversationSummary>('/api/conversations', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateConversation: (
    conversationId: string,
    payload: { title?: string; selected_agent_ids?: string[] },
  ) =>
    request<ConversationSummary>(`/api/conversations/${conversationId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  getConversation: (conversationId: string) =>
    request<ConversationDetail>(`/api/conversations/${conversationId}`),
  deleteConversation: (conversationId: string) =>
    request<void>(`/api/conversations/${conversationId}`, { method: 'DELETE' }),
  listMessages: (conversationId: string) =>
    request<ChatMessage[]>(`/api/conversations/${conversationId}/messages`),
  sendMessage: (conversationId: string, content: string) =>
    request<SendMessageResult>(`/api/conversations/${conversationId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    }),

  getTask: (taskId: string) => request<TaskState>(`/api/tasks/${taskId}`),
  stopTask: (taskId: string) =>
    request<TaskState>(`/api/tasks/${taskId}/stop`, { method: 'POST' }),
  resumeTask: (taskId: string) =>
    request<TaskState>(`/api/tasks/${taskId}/resume`, { method: 'POST' }),
  taskUsage: (taskId: string) => request<TaskUsage>(`/api/tasks/${taskId}/usage`),
  taskToolCalls: (taskId: string) => request<ToolCallRecord[]>(`/api/tasks/${taskId}/tool-calls`),

  eventsUrl: (conversationId: string, taskId: string, lastEventId: number) => {
    const params = new URLSearchParams({
      task_id: taskId,
      last_event_id: String(lastEventId),
    })
    return `${API_BASE}/api/conversations/${conversationId}/events?${params.toString()}`
  },
}
