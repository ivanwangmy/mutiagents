import { useMemo } from 'react'
import { Wrench } from 'lucide-react'
import type { AgentSummary, ChatMessage } from '../../types/classroom'
import { hexAlpha, formatClock } from '../../lib/format'
import { cn } from '../../lib/utils'
import { AgentAvatar } from './AgentAvatar'
import { Markdown } from './Markdown'
import { MessageFeedback } from './MessageFeedback'

const TYPE_META: Record<string, { label: string; className: string }> = {
  question: { label: '提问', className: 'bg-amber-50 text-amber-700' },
  response: { label: '发言', className: 'bg-muted text-muted-foreground' },
  message: { label: '发言', className: 'bg-muted text-muted-foreground' },
  challenge: { label: '质疑', className: 'bg-red-50 text-red-700' },
  request_help: { label: '求助', className: 'bg-sky-50 text-sky-700' },
  handoff: { label: '转交', className: 'bg-violet-50 text-violet-700' },
  conclusion: { label: '结论', className: 'bg-emerald-50 text-emerald-700' },
}

interface ToolBadge {
  tool: string
  ok: boolean
}

function readToolBadges(metadata: Record<string, unknown>): ToolBadge[] {
  const badges: ToolBadge[] = []
  const single = metadata.tool
  if (single && typeof single === 'object') {
    const item = single as { tool?: unknown; ok?: unknown }
    if (typeof item.tool === 'string') {
      badges.push({ tool: item.tool, ok: item.ok !== false })
    }
  }
  const list = metadata.tool_calls
  if (Array.isArray(list)) {
    for (const entry of list) {
      if (entry && typeof entry === 'object') {
        const item = entry as { tool?: unknown; ok?: unknown }
        if (typeof item.tool === 'string') {
          badges.push({ tool: item.tool, ok: item.ok !== false })
        }
      }
    }
  }
  return badges
}

export function MessageBubble({
  message,
  agents,
}: {
  message: ChatMessage
  agents: AgentSummary[]
}) {
  const tools = useMemo(() => readToolBadges(message.metadata ?? {}), [message.metadata])
  const agent = message.sender_agent_id
    ? agents.find((item) => item.id === message.sender_agent_id)
    : null
  const receiver = message.receiver_agent_id
    ? agents.find((item) => item.id === message.receiver_agent_id)
    : null

  if (message.sender_type === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[88%] sm:max-w-[76%]">
          <div className="mb-1 flex items-center justify-end gap-2 text-[11px] text-muted-foreground">
            <span>你</span>
            <span>{formatClock(message.created_at)}</span>
          </div>
          <div className="rounded-xl rounded-tr-sm border border-primary/15 bg-primary-soft px-4 py-3">
            <Markdown content={message.content} />
          </div>
        </div>
      </div>
    )
  }

  if (message.sender_type !== 'agent' || !agent) {
    return (
      <div className="rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
        {message.content}
      </div>
    )
  }

  const typeMeta = TYPE_META[message.message_type] ?? {
    label: message.message_type,
    className: 'bg-muted text-muted-foreground',
  }

  return (
    <div className="flex gap-2.5 sm:gap-3">
      <AgentAvatar agent={agent} size="md" className="mt-5" />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-sm font-semibold" style={{ color: hexAlpha(agent.theme_color, 1) }}>
            {agent.name}
          </span>
          <span
            className="rounded-full px-1.5 py-0.5 text-[10px]"
            style={{
              backgroundColor: hexAlpha(agent.theme_color, 0.12),
              color: agent.theme_color,
            }}
          >
            {agent.role_label}
          </span>
          <span className={cn('rounded-full px-1.5 py-0.5 text-[10px]', typeMeta.className)}>
            {typeMeta.label}
          </span>
          {receiver ? (
            <span className="text-[10px] text-muted-foreground">→ @{receiver.name}</span>
          ) : null}
          <span className="text-[11px] text-muted-foreground">{formatClock(message.created_at)}</span>
        </div>

        <div className="rounded-xl rounded-tl-sm border border-border bg-card px-4 py-3">
          <Markdown content={message.content} />
          {tools.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1.5 border-t border-border/70 pt-2">
              {tools.map((item, index) => (
                <span
                  key={`${item.tool}-${index}`}
                  className={cn(
                    'inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px]',
                    item.ok
                      ? 'bg-emerald-50 text-emerald-700'
                      : 'bg-red-50 text-red-700',
                  )}
                >
                  <Wrench className="h-2.5 w-2.5" />
                  {item.tool}
                  {item.ok ? '' : ' · 失败'}
                </span>
              ))}
            </div>
          ) : null}
          <MessageFeedback message={message} />
        </div>
      </div>
    </div>
  )
}
