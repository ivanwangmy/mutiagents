import { create } from 'zustand'
import { ApiError, api } from '../services/api'
import { STREAM_EVENT_TYPES } from '../types/classroom'
import type {
  AgentLiveStatus,
  AgentRuntimeStatus,
  AgentSummary,
  ChatMessage,
  ConversationDetail,
  ConversationSummary,
  LiveToolCall,
  StreamConnection,
  StreamEvent,
  TaskState,
  TaskUsage,
  ToolCallRecord,
} from '../types/classroom'

const TERMINAL_EVENTS = new Set(['task_completed', 'task_failed', 'task_stopped'])

let eventSource: EventSource | null = null
let streamToken = 0
let bootstrapPromise: Promise<void> | null = null

function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return '请求失败，请稍后重试'
}

function isActive(task: TaskState | null): boolean {
  return task?.status === 'pending' || task?.status === 'running'
}

function withStatus(
  map: Record<string, AgentLiveStatus>,
  agentId: string,
  status: AgentRuntimeStatus,
  detail?: string,
): Record<string, AgentLiveStatus> {
  return {
    ...map,
    [agentId]: { status, detail, updatedAt: Date.now() },
  }
}

function withDetail(
  map: Record<string, AgentLiveStatus>,
  agentId: string,
  detail: string,
): Record<string, AgentLiveStatus> {
  const current = map[agentId]
  if (!current) return map
  return { ...map, [agentId]: { ...current, detail, updatedAt: Date.now() } }
}

function upsertTool(
  list: LiveToolCall[],
  call: LiveToolCall,
): LiveToolCall[] {
  const index = list.findIndex((item) => item.call_id === call.call_id)
  if (index === -1) return [...list, call]
  const next = [...list]
  next[index] = { ...next[index], ...call }
  return next
}

export interface ClassroomState {
  agents: AgentSummary[]
  conversations: ConversationSummary[]
  activeConversation: ConversationSummary | null
  messages: ChatMessage[]
  selectedAgentIds: string[]
  task: TaskState | null
  usage: TaskUsage | null
  toolCalls: ToolCallRecord[]
  agentStatuses: Record<string, AgentLiveStatus>
  liveToolCalls: LiveToolCall[]
  connection: StreamConnection
  streaming: boolean
  activeTaskId: string | null
  loading: boolean
  messagesLoading: boolean
  submitting: boolean
  error: string | null

  bootstrap: () => Promise<void>
  refreshConversations: () => Promise<void>
  openConversation: (conversationId: string) => Promise<void>
  startConversation: (selectedAgentIds: string[], title?: string) => Promise<void>
  removeConversation: (conversationId: string) => Promise<void>
  toggleAgent: (agentId: string) => Promise<void>
  sendMessage: (content: string) => Promise<void>
  stopGeneration: () => Promise<void>
  resumeGeneration: () => Promise<void>
  clearError: () => void
}

export const useClassroomStore = create<ClassroomState>()((set, get) => {
  const closeStream = () => {
    streamToken += 1
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
  }

  const applyDetail = (detail: ConversationDetail) => {
    set({
      activeConversation: detail.conversation,
      messages: detail.messages,
      selectedAgentIds: detail.conversation.selected_agent_ids,
    })
  }

  const loadTaskMetrics = async (taskId: string) => {
    const [task, usage, toolCalls] = await Promise.all([
      api.getTask(taskId).catch(() => null),
      api.taskUsage(taskId).catch(() => null),
      api.taskToolCalls(taskId).catch(() => null),
    ])
    const patch: Partial<ClassroomState> = {}
    if (task) patch.task = task
    if (usage) patch.usage = usage
    if (toolCalls) patch.toolCalls = toolCalls
    set(patch)
  }

  const finalizeTask = async (event: StreamEvent, token: number) => {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    const taskId = event.task_id ?? get().activeTaskId
    const terminalStatus: AgentRuntimeStatus =
      event.event_type === 'task_failed'
        ? 'failed'
        : event.event_type === 'task_stopped'
          ? 'stopped'
          : 'completed'
    set((state) => {
      const agentStatuses = { ...state.agentStatuses }
      const participants =
        (state.task?.participating_agent_ids ?? []).length > 0
          ? state.task?.participating_agent_ids ?? []
          : Object.keys(agentStatuses)
      for (const agentId of participants) {
        agentStatuses[agentId] = {
          status: terminalStatus,
          detail:
            terminalStatus === 'completed'
              ? '本轮已完成'
              : terminalStatus === 'stopped'
                ? '已停止'
                : '任务失败',
          updatedAt: Date.now(),
        }
      }
      return { connection: 'closed', streaming: false, agentStatuses }
    })
    if (!taskId) return
    const [task, usage, toolCalls] = await Promise.all([
      api.getTask(taskId).catch(() => null),
      api.taskUsage(taskId).catch(() => null),
      api.taskToolCalls(taskId).catch(() => null),
    ])
    if (token !== streamToken) return
    const patch: Partial<ClassroomState> = { connection: 'closed', streaming: false }
    if (task) patch.task = task
    if (usage) patch.usage = usage
    if (toolCalls) patch.toolCalls = toolCalls
    set(patch)
    void get().refreshConversations()
  }

  const applyEvent = async (event: StreamEvent, token: number) => {
    if (token !== streamToken) return
    const payload = event.payload ?? {}
    switch (event.event_type) {
      case 'task_started': {
        set((state) => ({
          connection: 'live',
          streaming: true,
          activeTaskId: event.task_id ?? state.activeTaskId,
        }))
        return
      }
      case 'agent_started': {
        if (!event.agent_id) return
        set((state) => ({
          connection: 'live',
          agentStatuses: withStatus(state.agentStatuses, event.agent_id!, 'thinking', '正在思考'),
        }))
        return
      }
      case 'agent_status_changed': {
        const agentId = event.agent_id
        const status = payload.status
        if (!agentId || typeof status !== 'string') return
        set((state) => ({
          connection: 'live',
          agentStatuses: withStatus(
            state.agentStatuses,
            agentId,
            status as AgentRuntimeStatus,
            typeof payload.detail === 'string' ? payload.detail : undefined,
          ),
        }))
        return
      }
      case 'agent_message': {
        const message = payload.message as ChatMessage | undefined
        if (!message?.id) return
        set((state) => ({
          connection: 'live',
          messages: state.messages.some((item) => item.id === message.id)
            ? state.messages
            : [...state.messages, message],
        }))
        return
      }
      case 'agent_question':
      case 'agent_challenge':
      case 'agent_handoff': {
        if (!event.agent_id) return
        const detail =
          event.event_type === 'agent_question'
            ? '向用户提问'
            : event.event_type === 'agent_challenge'
              ? '提出质疑'
              : '已转交发言'
        set((state) => ({
          connection: 'live',
          agentStatuses: withDetail(state.agentStatuses, event.agent_id!, detail),
        }))
        return
      }
      case 'agent_tool_call':
      case 'tool_started': {
        const callId =
          typeof payload.call_id === 'string'
            ? payload.call_id
            : `${event.agent_id ?? 'agent'}:${String(payload.tool ?? '')}:${event.event_id}`
        if (!event.agent_id || typeof payload.tool !== 'string') return
        set((state) => ({
          connection: 'live',
          liveToolCalls: upsertTool(state.liveToolCalls, {
            call_id: callId,
            agent_id: event.agent_id!,
            tool: payload.tool as string,
            status: 'running',
          }),
        }))
        return
      }
      case 'skill_selected': {
        const callId =
          typeof payload.call_id === 'string'
            ? payload.call_id
            : `${event.agent_id ?? 'agent'}:${String(payload.skill ?? '')}:${event.event_id}`
        if (!event.agent_id || typeof payload.skill !== 'string') return
        set((state) => ({
          connection: 'live',
          liveToolCalls: upsertTool(state.liveToolCalls, {
            call_id: callId,
            agent_id: event.agent_id!,
            tool: `Skill · ${payload.skill}`,
            status: 'running',
          }),
        }))
        return
      }
      case 'skill_loaded':
      case 'skill_completed': {
        const callId = typeof payload.call_id === 'string' ? payload.call_id : ''
        if (!callId) return
        const steps = Array.isArray(payload.steps) ? payload.steps.length : 0
        set((state) => ({
          connection: 'live',
          liveToolCalls: upsertTool(state.liveToolCalls, {
            call_id: callId,
            agent_id: event.agent_id ?? '',
            tool: typeof payload.skill === 'string' ? `Skill · ${payload.skill}` : 'Skill',
            status: 'success',
            result: steps > 0 ? `已加载 ${steps} 个执行步骤` : undefined,
          }),
        }))
        return
      }
      case 'skill_failed': {
        const callId = typeof payload.call_id === 'string' ? payload.call_id : ''
        if (!callId) return
        set((state) => ({
          connection: 'live',
          liveToolCalls: upsertTool(state.liveToolCalls, {
            call_id: callId,
            agent_id: event.agent_id ?? '',
            tool: typeof payload.skill === 'string' ? `Skill · ${payload.skill}` : 'Skill',
            status: 'failed',
            error: typeof payload.error === 'string' ? payload.error : null,
          }),
        }))
        return
      }
      case 'tool_call_started': {
        const callId = typeof payload.call_id === 'string' ? payload.call_id : ''
        if (!event.agent_id || !callId || typeof payload.tool !== 'string') return
        set((state) => ({
          connection: 'live',
          liveToolCalls: upsertTool(state.liveToolCalls, {
            call_id: callId,
            agent_id: event.agent_id!,
            tool: payload.tool as string,
            status: 'running',
          }),
        }))
        return
      }
      case 'tool_call_completed':
      case 'tool_call_failed': {
        const callId = typeof payload.call_id === 'string' ? payload.call_id : ''
        if (!callId) return
        set((state) => ({
          connection: 'live',
          liveToolCalls: upsertTool(state.liveToolCalls, {
            call_id: callId,
            agent_id: event.agent_id ?? '',
            tool: typeof payload.tool === 'string' ? (payload.tool as string) : '',
            status: event.event_type === 'tool_call_completed' ? 'success' : 'failed',
            duration_ms:
              typeof payload.duration_ms === 'number' ? payload.duration_ms : undefined,
            error: typeof payload.error === 'string' ? payload.error : null,
            result:
              typeof payload.result_preview === 'string' ? payload.result_preview : undefined,
          }),
        }))
        return
      }
      case 'tool_completed':
      case 'tool_failed': {
        const callId = typeof payload.call_id === 'string' ? payload.call_id : ''
        if (!callId) return
        set((state) => ({
          connection: 'live',
          liveToolCalls: upsertTool(state.liveToolCalls, {
            call_id: callId,
            agent_id: event.agent_id ?? '',
            tool: typeof payload.tool === 'string' ? (payload.tool as string) : '',
            status: event.event_type === 'tool_completed' ? 'success' : 'failed',
            duration_ms:
              typeof payload.duration_ms === 'number' ? payload.duration_ms : undefined,
            error: typeof payload.error === 'string' ? payload.error : null,
            result: typeof payload.result === 'string' ? payload.result : undefined,
          }),
        }))
        return
      }
      case 'agent_waiting': {
        if (!event.agent_id) return
        set((state) => ({
          connection: 'live',
          agentStatuses: withStatus(state.agentStatuses, event.agent_id!, 'waiting', '等待中'),
        }))
        return
      }
      case 'agent_failed': {
        if (!event.agent_id) return
        set((state) => ({
          connection: 'live',
          agentStatuses: withStatus(
            state.agentStatuses,
            event.agent_id!,
            'failed',
            typeof payload.error === 'string' ? payload.error : '执行失败',
          ),
        }))
        return
      }
      case 'agent_completed': {
        if (!event.agent_id) return
        set((state) => ({
          connection: 'live',
          agentStatuses: withStatus(
            state.agentStatuses,
            event.agent_id!,
            'completed',
            '已结束本轮',
          ),
        }))
        return
      }
      case 'conversation_started': {
        void get().refreshConversations()
        return
      }
      default:
        break
    }
    if (TERMINAL_EVENTS.has(event.event_type)) {
      await finalizeTask(event, token)
      return
    }
    set({ connection: 'live' })
  }

  const startStream = (conversationId: string, taskId: string) => {
    closeStream()
    const token = streamToken
    set({
      task: null,
      usage: null,
      toolCalls: [],
      agentStatuses: {},
      liveToolCalls: [],
      connection: 'connecting',
      streaming: true,
      activeTaskId: taskId,
    })
    void api
      .getTask(taskId)
      .then((task) => {
        if (token === streamToken) set({ task })
      })
      .catch(() => undefined)

    const source = new EventSource(api.eventsUrl(conversationId, taskId, 0))
    eventSource = source
    source.onopen = () => {
      if (token === streamToken) set({ connection: 'live' })
    }
    source.onerror = () => {
      if (token !== streamToken) return
      set({
        connection: source.readyState === EventSource.CLOSED ? 'closed' : 'reconnecting',
      })
    }
    for (const type of STREAM_EVENT_TYPES) {
      source.addEventListener(type, (raw) => {
        if (token !== streamToken) return
        try {
          const event = JSON.parse((raw as MessageEvent<string>).data) as StreamEvent
          void applyEvent(event, token)
        } catch {
          // 忽略无法解析的事件，不中断数据流
        }
      })
    }
  }

  const syncLatestTask = async (messages: ChatMessage[]) => {
    const lastTaskId = [...messages].reverse().find((item) => item.task_id)?.task_id
    if (!lastTaskId) return
    await loadTaskMetrics(lastTaskId)
  }

  return {
    agents: [],
    conversations: [],
    activeConversation: null,
    messages: [],
    selectedAgentIds: [],
    task: null,
    usage: null,
    toolCalls: [],
    agentStatuses: {},
    liveToolCalls: [],
    connection: 'idle',
    streaming: false,
    activeTaskId: null,
    loading: false,
    messagesLoading: false,
    submitting: false,
    error: null,

    clearError: () => set({ error: null }),

    bootstrap: () => {
      if (bootstrapPromise) return bootstrapPromise
      bootstrapPromise = (async () => {
        set({ loading: true, error: null })
        try {
          const [agents, conversations] = await Promise.all([
            api.listAgents(),
            api.listConversations(),
          ])
          set({ agents, conversations })
          if (!get().activeConversation && conversations.length > 0) {
            await get().openConversation(conversations[0].id)
          }
        } catch (error) {
          set({ error: messageOf(error) })
        } finally {
          set({ loading: false })
        }
      })().finally(() => {
        bootstrapPromise = null
      })
      return bootstrapPromise
    },

    refreshConversations: async () => {
      try {
        const conversations = await api.listConversations()
        set((state) => {
          const active =
            conversations.find((item) => item.id === state.activeConversation?.id) ??
            state.activeConversation
          return { conversations, activeConversation: active }
        })
      } catch {
        // 列表刷新失败不覆盖当前课堂
      }
    },

    openConversation: async (conversationId) => {
      closeStream()
      set({
        messagesLoading: true,
        error: null,
        messages: [],
        task: null,
        usage: null,
        toolCalls: [],
        agentStatuses: {},
        liveToolCalls: [],
        connection: 'idle',
        streaming: false,
        activeTaskId: null,
        submitting: false,
      })
      try {
        const detail = await api.getConversation(conversationId)
        applyDetail(detail)
        set({ messagesLoading: false })
        if (detail.active_task_id) {
          startStream(conversationId, detail.active_task_id)
        } else {
          await syncLatestTask(detail.messages)
        }
      } catch (error) {
        set({ error: messageOf(error), messagesLoading: false })
      }
    },

    startConversation: async (selectedAgentIds, title) => {
      set({ submitting: true, error: null })
      try {
        const conversation = await api.createConversation({
          title: title?.trim() || undefined,
          selected_agent_ids: selectedAgentIds,
        })
        closeStream()
        set((state) => ({
          conversations: [conversation, ...state.conversations],
          activeConversation: conversation,
          messages: [],
          selectedAgentIds: conversation.selected_agent_ids,
          task: null,
          usage: null,
          toolCalls: [],
          agentStatuses: {},
          liveToolCalls: [],
          connection: 'idle',
          streaming: false,
          activeTaskId: null,
          submitting: false,
        }))
      } catch (error) {
        set({ error: messageOf(error), submitting: false })
        throw error
      }
    },

    removeConversation: async (conversationId) => {
      try {
        await api.deleteConversation(conversationId)
      } catch (error) {
        set({ error: messageOf(error) })
        return
      }
      closeStream()
      const remaining = get().conversations.filter((item) => item.id !== conversationId)
      set({
        conversations: remaining,
        activeConversation: null,
        messages: [],
        selectedAgentIds: [],
        task: null,
        usage: null,
        toolCalls: [],
        agentStatuses: {},
        liveToolCalls: [],
        connection: 'idle',
        streaming: false,
        activeTaskId: null,
      })
      if (remaining.length > 0) {
        await get().openConversation(remaining[0].id)
      }
    },

    toggleAgent: async (agentId) => {
      const conversation = get().activeConversation
      if (!conversation) return
      if (get().submitting || isActive(get().task) || get().streaming) return
      const current = get().selectedAgentIds
      const next = current.includes(agentId)
        ? current.filter((item) => item !== agentId)
        : [...current, agentId]
      if (next.length === 0) {
        set({ error: '至少需要选择一个 Agent' })
        return
      }
      const ordered = get()
        .agents.filter((agent) => next.includes(agent.id))
        .map((agent) => agent.id)
      set({ selectedAgentIds: ordered, error: null })
      try {
        const updated = await api.updateConversation(conversation.id, {
          selected_agent_ids: ordered,
        })
        set((state) => ({
          activeConversation: updated,
          selectedAgentIds: updated.selected_agent_ids,
          conversations: state.conversations.map((item) =>
            item.id === updated.id ? { ...item, ...updated } : item,
          ),
        }))
      } catch (error) {
        set({ selectedAgentIds: current, error: messageOf(error) })
      }
    },

    sendMessage: async (content) => {
      const conversation = get().activeConversation
      const text = content.trim()
      if (!conversation || !text) return
      if (get().selectedAgentIds.length === 0) {
        set({ error: '至少选择一个 Agent 才能提交问题' })
        return
      }
      if (get().submitting || get().streaming || isActive(get().task)) return
      set({ submitting: true, error: null })
      try {
        const result = await api.sendMessage(conversation.id, text)
        set((state) => ({
          messages: [...state.messages, result.user_message],
          submitting: false,
        }))
        startStream(conversation.id, result.task_id)
        void get().refreshConversations()
      } catch (error) {
        set({ error: messageOf(error), submitting: false })
      }
    },

    stopGeneration: async () => {
      const task = get().task
      if (!task || !isActive(task)) return
      try {
        const updated = await api.stopTask(task.id)
        set({ task: updated })
      } catch (error) {
        set({ error: messageOf(error) })
      }
    },

    resumeGeneration: async () => {
      const task = get().task
      if (!task || (task.status !== 'stopped' && task.status !== 'failed')) return
      set({ submitting: true, error: null })
      try {
        const updated = await api.resumeTask(task.id)
        set({ submitting: false })
        startStream(updated.conversation_id, updated.id)
      } catch (error) {
        set({ error: messageOf(error), submitting: false })
      }
    },
  }
})

export function selectIsRunning(state: ClassroomState): boolean {
  return (
    state.submitting ||
    state.streaming ||
    state.task?.status === 'pending' ||
    state.task?.status === 'running'
  )
}
