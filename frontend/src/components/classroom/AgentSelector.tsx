import { useState } from 'react'
import { Check, Info, Wrench } from 'lucide-react'
import type { AgentLiveStatus, AgentSummary } from '../../types/classroom'
import { useClassroomStore, selectIsRunning } from '../../store/classroom'
import { cn } from '../../lib/utils'
import { AgentAvatar } from './AgentAvatar'
import { AgentProfile } from './AgentProfile'

const STATUS_BADGE: Record<string, { label: string; className: string }> = {
  thinking: { label: '处理中', className: 'bg-sky-50 text-sky-700' },
  speaking: { label: '发言中', className: 'bg-emerald-50 text-emerald-700' },
  tool_calling: { label: '调用工具', className: 'bg-violet-50 text-violet-700' },
  waiting: { label: '等待中', className: 'bg-amber-50 text-amber-700' },
  completed: { label: '已完成', className: 'bg-muted text-muted-foreground' },
  failed: { label: '失败', className: 'bg-red-50 text-red-700' },
  stopped: { label: '已停止', className: 'bg-amber-50 text-amber-700' },
}

function AgentCard({
  agent,
  selected,
  locked,
  live,
  toolLabel,
  onToggle,
  onOpenProfile,
}: {
  agent: AgentSummary
  selected: boolean
  locked: boolean
  live?: AgentLiveStatus
  toolLabel: string | null
  onToggle: () => void
  onOpenProfile: () => void
}) {
  const badge = live ? STATUS_BADGE[live.status] : undefined
  return (
    <div
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={locked ? undefined : onToggle}
      onKeyDown={(event) => {
        if (locked) return
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onToggle()
        }
      }}
      title={locked ? '讨论进行中，暂不能调整参与者' : undefined}
      className={cn(
        'group relative rounded-xl border p-3 transition-colors',
        selected
          ? 'border-primary/35 bg-primary-soft/60'
          : 'border-border bg-card hover:border-primary/25 hover:bg-muted/40',
        locked ? 'cursor-not-allowed opacity-75' : 'cursor-pointer',
      )}
    >
      <div className="flex items-start gap-2.5">
        <AgentAvatar agent={agent} size="md" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm font-medium">{agent.name}</span>
            <span className="shrink-0 rounded-full border border-border bg-card px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {agent.role_label}
            </span>
            {badge ? (
              <span
                title={live?.detail}
                className={cn(
                  'shrink-0 rounded-full px-1.5 py-0.5 text-[10px]',
                  badge.className,
                )}
              >
                {badge.label}
              </span>
            ) : null}
          </div>
          <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">
            {agent.short_description}
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {agent.personality_tags.slice(0, 2).map((tag) => (
              <span
                key={tag}
                className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
        <span
          className={cn(
            'flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors',
            selected
              ? 'border-primary bg-primary text-primary-foreground'
              : 'border-border bg-card text-transparent',
          )}
        >
          <Check className="h-3 w-3" />
        </span>
      </div>

      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="text-[11px] text-muted-foreground">
          {selected ? '参与本轮课堂' : '未参与'}
        </span>
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            onOpenProfile()
          }}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-card hover:text-primary"
        >
          <Info className="h-3 w-3" />
          查看资料
        </button>
      </div>

      {toolLabel ? (
        <p className="mt-2 flex items-center gap-1 rounded-md bg-muted/70 px-2 py-1 text-[10px] text-muted-foreground">
          <Wrench className="h-3 w-3" />
          <span className="truncate">{toolLabel}</span>
        </p>
      ) : null}
    </div>
  )
}

export function AgentSelector() {
  const agents = useClassroomStore((state) => state.agents)
  const selectedAgentIds = useClassroomStore((state) => state.selectedAgentIds)
  const toggleAgent = useClassroomStore((state) => state.toggleAgent)
  const toolCalls = useClassroomStore((state) => state.toolCalls)
  const liveToolCalls = useClassroomStore((state) => state.liveToolCalls)
  const agentStatuses = useClassroomStore((state) => state.agentStatuses)
  const isRunning = useClassroomStore(selectIsRunning)
  const [profileAgent, setProfileAgent] = useState<AgentSummary | null>(null)

  const locked = isRunning

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-muted-foreground">课堂参与者</h3>
        <span className="text-[11px] text-muted-foreground">
          {selectedAgentIds.length}/3 已选择
        </span>
      </div>

      {agents.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
          正在加载 Agent 配置…
        </p>
      ) : (
        <div className="space-y-2">
          {agents.map((agent) => {
            const latestTool = [...toolCalls]
              .reverse()
              .find((call) => call.agent_id === agent.id)
            const liveTool = [...liveToolCalls]
              .reverse()
              .find((call) => call.agent_id === agent.id)
            const toolLabel = liveTool
              ? `${liveTool.tool} · ${
                  liveTool.status === 'running'
                    ? '执行中'
                    : liveTool.status === 'success'
                      ? '成功'
                      : '失败'
                }`
              : latestTool
                ? `${latestTool.tool_name} · ${latestTool.status === 'success' ? '成功' : '失败'}`
                : null
            return (
              <AgentCard
                key={agent.id}
                agent={agent}
                selected={selectedAgentIds.includes(agent.id)}
                locked={locked}
                live={
                  selectedAgentIds.includes(agent.id)
                    ? agentStatuses[agent.id]
                    : undefined
                }
                toolLabel={toolLabel}
                onToggle={() => void toggleAgent(agent.id)}
                onOpenProfile={() => setProfileAgent(agent)}
              />
            )
          })}
        </div>
      )}

      <p className="text-[11px] leading-relaxed text-muted-foreground">
        点击卡片选择或取消参与者，至少保留 1 个；调整后立即生效。
      </p>

      <AgentProfile
        agent={profileAgent}
        open={profileAgent !== null}
        onOpenChange={(open) => {
          if (!open) setProfileAgent(null)
        }}
        selected={profileAgent ? selectedAgentIds.includes(profileAgent.id) : false}
        onToggle={() => {
          if (profileAgent) void toggleAgent(profileAgent.id)
        }}
      />
    </section>
  )
}
