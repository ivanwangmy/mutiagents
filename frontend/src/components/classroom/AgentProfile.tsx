import { Wrench } from 'lucide-react'
import type { AgentSummary } from '../../types/classroom'
import { hexAlpha } from '../../lib/format'
import { AgentAvatar } from './AgentAvatar'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/dialog'

export function AgentProfile({
  agent,
  open,
  onOpenChange,
  selected,
  onToggle,
}: {
  agent: AgentSummary | null
  open: boolean
  onOpenChange: (open: boolean) => void
  selected: boolean
  onToggle: () => void
}) {
  if (!agent) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="left-1/2 top-1/2 max-h-[86vh] w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl p-0 shadow-xl scrollbar-thin">
        <div className="border-b border-border px-6 pb-5 pt-6">
          <div className="flex items-start gap-4">
            <AgentAvatar agent={agent} size="xl" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <DialogTitle className="text-lg">{agent.name}</DialogTitle>
                <Badge
                  style={{
                    backgroundColor: hexAlpha(agent.theme_color, 0.12),
                    color: agent.theme_color,
                  }}
                  className="border-transparent"
                >
                  {agent.role_label}
                </Badge>
                <Badge variant={selected ? 'success' : 'outline'}>
                  {selected ? '已参与' : '未参与'}
                </Badge>
              </div>
              <DialogDescription className="mt-1.5">{agent.short_description}</DialogDescription>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-1.5">
            {agent.personality_tags.map((tag) => (
              <span
                key={tag}
                className="rounded-full border border-border bg-muted px-2 py-0.5 text-[11px] text-muted-foreground"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>

        <div className="space-y-5 px-6 py-5">
          <section>
            <h4 className="text-xs font-semibold text-muted-foreground">角色介绍</h4>
            <p className="mt-1.5 text-sm leading-relaxed text-foreground/90">{agent.introduction}</p>
          </section>

          <section>
            <h4 className="text-xs font-semibold text-muted-foreground">运行参数</h4>
            <dl className="mt-2 grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-lg border border-border bg-muted/40 px-3 py-2">
                <dt className="text-muted-foreground">模型</dt>
                <dd className="mt-0.5 font-medium">{agent.runtime.model}</dd>
              </div>
              <div className="rounded-lg border border-border bg-muted/40 px-3 py-2">
                <dt className="text-muted-foreground">温度</dt>
                <dd className="mt-0.5 font-medium">{agent.runtime.temperature}</dd>
              </div>
              <div className="rounded-lg border border-border bg-muted/40 px-3 py-2">
                <dt className="text-muted-foreground">单次输出上限</dt>
                <dd className="mt-0.5 font-medium">{agent.runtime.max_output_tokens} tokens</dd>
              </div>
              <div className="rounded-lg border border-border bg-muted/40 px-3 py-2">
                <dt className="text-muted-foreground">上下文上限</dt>
                <dd className="mt-0.5 font-medium">{agent.runtime.max_context_tokens} tokens</dd>
              </div>
            </dl>
          </section>

          <section>
            <h4 className="text-xs font-semibold text-muted-foreground">
              Skills（{agent.skills.length}）
            </h4>
            <ul className="mt-2 space-y-2">
              {agent.skills.map((skill) => (
                <li key={skill.name} className="rounded-lg border border-border px-3 py-2">
                  <p className="text-xs font-medium">{skill.name}</p>
                  <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                    {skill.description}
                  </p>
                  {skill.when_to_use ? (
                    <p className="mt-1 text-[11px] text-muted-foreground/80">
                      适用：{skill.when_to_use}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h4 className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
              <Wrench className="h-3.5 w-3.5" />
              可用工具
            </h4>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {agent.tool_permissions.length > 0 ? (
                agent.tool_permissions.map((tool) => (
                  <span
                    key={tool}
                    className="rounded-md border border-border bg-muted px-2 py-0.5 font-mono text-[11px] text-muted-foreground"
                  >
                    {tool}
                  </span>
                ))
              ) : (
                <span className="text-xs text-muted-foreground">无</span>
              )}
            </div>
          </section>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border px-6 py-4">
          <p className="text-[11px] text-muted-foreground">
            {selected ? '点击取消后，该 Agent 不参与后续提问' : '点击加入后，该 Agent 将参与后续提问'}
          </p>
          <Button variant={selected ? 'outline' : 'default'} size="sm" onClick={onToggle}>
            {selected ? '取消参与' : '加入课堂'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
