export interface SkillInfo {
  name: string
  description: string
  execution_logic: string
  when_to_use: string
}

export interface AgentRuntimeInfo {
  model: string
  temperature: number
  max_output_tokens: number
  max_context_tokens: number
}

export interface AgentSummary {
  id: string
  name: string
  role: 'teacher' | 'assistant' | 'student' | string
  role_label: string
  avatar: string
  theme_color: string
  short_description: string
  introduction: string
  personality_tags: string[]
  skills: SkillInfo[]
  runtime: AgentRuntimeInfo
  tool_permissions: string[]
}

export interface ConversationSummary {
  id: string
  title: string
  selected_agent_ids: string[]
  status: string
  created_at: string
  updated_at: string
  last_message: string | null
}

export interface ConversationAgentBrief {
  id: string
  name: string
  role_label: string
  avatar: string
  theme_color: string
}

export interface ConversationDetail {
  conversation: ConversationSummary
  messages: ChatMessage[]
  agents: ConversationAgentBrief[]
  active_task_id: string | null
}

export type AgentRuntimeStatus =
  | 'idle'
  | 'thinking'
  | 'speaking'
  | 'tool_calling'
  | 'waiting'
  | 'completed'
  | 'failed'
  | 'stopped'

export interface AgentLiveStatus {
  status: AgentRuntimeStatus
  detail?: string
  updatedAt: number
}

export type StreamConnection = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'closed'

export interface StreamEvent {
  event_id: number
  event_type: string
  conversation_id: string
  task_id: string | null
  agent_id: string | null
  timestamp: string
  payload: Record<string, unknown>
}

export interface LiveToolCall {
  call_id: string
  agent_id: string
  tool: string
  status: 'running' | 'success' | 'failed'
  duration_ms?: number
  error?: string | null
  result?: string
}

export const STREAM_EVENT_TYPES = [
  'conversation_started',
  'task_started',
  'agent_started',
  'agent_status_changed',
  'agent_message',
  'agent_question',
  'agent_challenge',
  'agent_handoff',
  'agent_tool_call',
  'tool_started',
  'tool_completed',
  'tool_failed',
  'tool_call_started',
  'tool_call_completed',
  'tool_call_failed',
  'skill_selected',
  'skill_loaded',
  'skill_completed',
  'skill_failed',
  'agent_waiting',
  'agent_completed',
  'agent_failed',
  'task_completed',
  'task_failed',
  'task_stopped',
] as const

export type ExperienceStatus = 'candidate' | 'validated' | 'rejected'

export type ExperienceType =
  | 'task_result'
  | 'tool_usage'
  | 'user_feedback'
  | 'collaboration'
  | 'knowledge_correction'

export interface AgentExperience {
  id: string
  agent_id: string
  experience_type: ExperienceType | string
  content: string
  source_conversation_id: string | null
  source_task_id: string | null
  confidence: number
  validation_status: ExperienceStatus | string
  validation_note: string | null
  keywords: string[]
  use_count: number
  last_used_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ExperienceList {
  agent_id: string
  total: number
  counts: Record<string, number>
  experiences: AgentExperience[]
}

export interface FeedbackResult {
  id: string
  conversation_id: string
  message_id: string | null
  agent_id: string
  rating: number
  comment: string
  created_at: string
  experience: AgentExperience | null
}

export interface ToolCallMeta {
  tool?: string
  ok?: boolean
  error?: string | null
  duration_ms?: number
  summary_skipped?: string
}

export interface ChatMessage {
  id: string
  conversation_id: string
  task_id: string | null
  sender_type: 'user' | 'agent' | 'system' | string
  sender_agent_id: string | null
  receiver_agent_id: string | null
  message_type: string
  content: string
  reply_to_message_id: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export interface SendMessageResult {
  task_id: string
  user_message: ChatMessage
  status: string
}

export interface TaskState {
  id: string
  conversation_id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'stopped' | string
  participating_agent_ids: string[]
  turn_count: number
  message_count: number
  model_calls: number
  prompt_tokens: number
  completion_tokens: number
  stop_reason: string | null
  error: string | null
  assistant_message_id: string | null
  started_at: string
  finished_at: string | null
}

export interface TaskUsage {
  task_id: string
  model_calls: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  token_budget: number
  seconds_elapsed: number
}

export interface ToolCallRecord {
  id: number
  agent_id: string
  tool_name: string
  arguments: Record<string, unknown>
  result: unknown
  status: string
  error: string | null
  duration_ms: number | null
  created_at: string
}
