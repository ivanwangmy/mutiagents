import { Clock3, Cpu, Wrench } from 'lucide-react'
import { useClassroomStore } from '../../store/classroom'
import { cn } from '../../lib/utils'
import { AgentAvatar } from './AgentAvatar'

const STATUS_LABEL: Record<string, string> = {
  pending: '排队中',
  running: '讨论进行中',
  completed: '已完成',
  stopped: '已停止',
  failed: '失败',
}

const REASON_LABEL: Record<string, string> = {
  finish: '正常结束',
  token_budget: 'Token 预算耗尽',
  max_turns: '达到轮次上限',
  max_model_calls: '达到调用次数上限',
  max_seconds: '达到时间上限',
  max_messages: '达到消息数上限',
  consecutive_waits: '连续无有效发言',
  stopped: '用户停止',
}

const AGENT_STATUS_LABEL: Record<string, string> = {
  thinking: '处理中',
  speaking: '发言中',
  tool_calling: '调用工具',
  waiting: '等待其他 Agent',
  completed: '已完成',
  failed: '失败',
  stopped: '已停止',
}

const CONNECTION_LABEL: Record<string, string> = {
  idle: '未连接',
  connecting: '连接中',
  live: '实时已连接',
  reconnecting: '断线重连中',
  closed: '连接已关闭',
}

export function AgentStatusPanel() {
  const agents = useClassroomStore((state) => state.agents)
  const task = useClassroomStore((state) => state.task)
  const usage = useClassroomStore((state) => state.usage)
  const toolCalls = useClassroomStore((state) => state.toolCalls)
  const liveToolCalls = useClassroomStore((state) => state.liveToolCalls)
  const agentStatuses = useClassroomStore((state) => state.agentStatuses)
  const connection = useClassroomStore((state) => state.connection)
  const selectedAgentIds = useClassroomStore((state) => state.selectedAgentIds)
  const activeConversation = useClassroomStore((state) => state.activeConversation)
  const submitting = useClassroomStore((state) => state.submitting)

  const participants = agents.filter((agent) => selectedAgentIds.includes(agent.id))
  const status = submitting ? 'running' : task?.status
  const tokens = usage?.total_tokens ?? (task ? task.prompt_tokens + task.completion_tokens : 0)
  const budget = usage?.token_budget
  const ratio = budget && budget > 0 ? Math.min(tokens / budget, 1) : 0
  const latestTools =
    liveToolCalls.length > 0
      ? liveToolCalls.slice(-3).reverse().map((call) => ({
          key: call.call_id,
          agent_id: call.agent_id,
          tool_name: call.tool,
          status:
            call.status === 'success' ? 'success' : call.status === 'failed' ? 'failed' : 'running',
        }))
      : toolCalls.slice(-3).reverse().map((call) => ({
          key: String(call.id),
          agent_id: call.agent_id,
          tool_name: call.tool_name,
          status: call.status,
        }))
  const agentName = (id: string) => agents.find((agent) => agent.id === id)?.name ?? id
  const taskActive = status === 'pending' || status === 'running'
  const showConnection =
    connection !== 'idle' && !(connection === 'closed' && !taskActive)

  return (
    <section className="rounded-xl border border-border bg-card p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold text-muted-foreground">课堂状态</h3>
        <div className="flex items-center gap-1.5">
          {showConnection ? (
            <span
              className={cn(
                'inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px]',
                connection === 'live'
                  ? 'bg-emerald-50 text-emerald-700'
                  : connection === 'reconnecting'
                    ? 'bg-amber-50 text-amber-700'
                    : connection === 'closed'
                      ? 'bg-muted text-muted-foreground'
                      : 'bg-sky-50 text-sky-700',
              )}
            >
              <span
                className={cn(
                  'h-1 w-1 rounded-full',
                  connection === 'live'
                    ? 'bg-emerald-500'
                    : connection === 'reconnecting'
                      ? 'bg-amber-500'
                      : connection === 'closed'
                        ? 'bg-slate-300'
                        : 'bg-sky-500',
                )}
              />
              {CONNECTION_LABEL[connection] ?? connection}
            </span>
          ) : null}
          <span
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px]',
            status === 'running' || status === 'pending'
              ? 'bg-emerald-50 text-emerald-700'
              : status === 'failed'
                ? 'bg-red-50 text-red-700'
                : status === 'stopped'
                  ? 'bg-amber-50 text-amber-700'
                  : 'bg-muted text-muted-foreground',
          )}
        >
          <span
            className={cn(
              'h-1.5 w-1.5 rounded-full',
              status === 'running' || status === 'pending'
                ? 'bg-emerald-500'
                : status === 'failed'
                  ? 'bg-red-500'
                  : status === 'stopped'
                    ? 'bg-amber-500'
                    : 'bg-slate-300',
            )}
          />
          {status ? (STATUS_LABEL[status] ?? status) : activeConversation ? '待提问' : '未开始'}
        </span>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2">
        {participants.length > 0 ? (
          <>
            <div className="flex -space-x-1.5">
              {participants.map((agent) => (
                <AgentAvatar key={agent.id} agent={agent} size="sm" />
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground">
              {participants.map((agent) => agent.name).join('、')}
            </p>
          </>
        ) : (
          <p className="text-[11px] text-muted-foreground">尚未选择参与者</p>
        )}
      </div>

      {participants.some((agent) => agentStatuses[agent.id]) ? (
        <ul className="mt-2 space-y-1 border-t border-border pt-2">
          {participants.map((agent) => {
            const live = agentStatuses[agent.id]
            if (!live) return null
            return (
              <li
                key={agent.id}
                className="flex items-center justify-between gap-2 text-[11px]"
              >
                <span className="truncate text-muted-foreground">
                  {agent.name}
                  {live.detail ? (
                    <span className="text-muted-foreground/70"> · {live.detail}</span>
                  ) : null}
                </span>
                <span
                  className={cn(
                    'shrink-0',
                    live.status === 'speaking'
                      ? 'text-emerald-600'
                      : live.status === 'tool_calling'
                        ? 'text-violet-600'
                        : live.status === 'failed'
                          ? 'text-red-600'
                          : live.status === 'completed'
                            ? 'text-muted-foreground'
                            : 'text-amber-600',
                  )}
                >
                  {AGENT_STATUS_LABEL[live.status] ?? live.status}
                </span>
              </li>
            )
          })}
        </ul>
      ) : null}

      {task ? (
        <div className="mt-3 space-y-2">
          <div>
            <div className="flex items-center justify-between text-[11px] text-muted-foreground">
              <span>本轮 Token</span>
              <span>
                {tokens}
                {budget ? ` / ${budget}` : ''}
              </span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className={cn(
                  'h-full rounded-full transition-all',
                  ratio > 0.85 ? 'bg-amber-500' : 'bg-primary',
                )}
                style={{ width: `${Math.max(ratio * 100, tokens > 0 ? 4 : 0)}%` }}
              />
            </div>
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <Cpu className="h-3 w-3" />
              模型调用 {task.model_calls}
            </span>
            <span className="inline-flex items-center gap-1">
              <Clock3 className="h-3 w-3" />
              {usage ? `${usage.seconds_elapsed}s` : task.status === 'running' ? '计时中' : '—'}
            </span>
            <span>发言 {task.message_count}</span>
          </div>
          {task.stop_reason ? (
            <p className="text-[11px] text-muted-foreground">
              结束原因：{REASON_LABEL[task.stop_reason] ?? task.stop_reason}
            </p>
          ) : null}
          {task.error ? (
            <p className="rounded-md bg-red-50 px-2 py-1 text-[11px] leading-relaxed text-red-700">
              {task.error}
            </p>
          ) : null}
        </div>
      ) : (
        <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
          {activeConversation
            ? '提出第一个问题后，这里会显示真实的调用与 Token 统计。'
            : '新建课堂并选择参与者后开始讨论。'}
        </p>
      )}

      {latestTools.length > 0 ? (
        <div className="mt-3 border-t border-border pt-2">
          <p className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
            <Wrench className="h-3 w-3" />
            最近工具调用
          </p>
          <ul className="mt-1 space-y-1">
            {latestTools.map((call) => (
              <li key={call.key} className="flex items-center justify-between gap-2 text-[11px]">
                <span className="truncate">
                  {agentName(call.agent_id)} · {call.tool_name}
                </span>
                <span
                  className={cn(
                    'shrink-0',
                    call.status === 'success'
                      ? 'text-emerald-600'
                      : call.status === 'running'
                        ? 'text-sky-600'
                        : 'text-red-600',
                  )}
                >
                  {call.status === 'success'
                    ? '成功'
                    : call.status === 'running'
                      ? '执行中'
                      : '失败'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  )
}
