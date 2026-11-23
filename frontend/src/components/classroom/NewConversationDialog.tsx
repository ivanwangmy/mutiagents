import { useEffect, useState } from 'react'
import { Check } from 'lucide-react'
import { useClassroomStore } from '../../store/classroom'
import { cn } from '../../lib/utils'
import { AgentAvatar } from './AgentAvatar'
import { Button } from '../ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/dialog'

export function NewConversationDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const agents = useClassroomStore((state) => state.agents)
  const startConversation = useClassroomStore((state) => state.startConversation)
  const submitting = useClassroomStore((state) => state.submitting)
  const [title, setTitle] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setTitle('')
    setSelected(agents.map((agent) => agent.id))
    setError(null)
  }, [open, agents])

  const toggle = (agentId: string) => {
    setSelected((current) => {
      if (current.includes(agentId)) {
        if (current.length === 1) {
          setError('至少选择一个 Agent')
          return current
        }
        setError(null)
        return current.filter((item) => item !== agentId)
      }
      setError(null)
      return agents.filter((agent) => current.includes(agent.id) || agent.id === agentId).map((agent) => agent.id)
    })
  }

  const create = async () => {
    if (selected.length === 0) {
      setError('至少选择一个 Agent')
      return
    }
    try {
      await startConversation(selected, title)
      onOpenChange(false)
    } catch {
      setError('创建失败，请检查后端服务')
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="left-1/2 top-1/2 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl p-6 shadow-xl">
        <DialogTitle>新建课堂</DialogTitle>
        <DialogDescription className="mt-1">
          为本次对话命名并选择参与者，创建后立即进入课堂。
        </DialogDescription>

        <label className="mt-5 block text-xs font-medium text-muted-foreground" htmlFor="classroom-title">
          对话名称（可选）
        </label>
        <input
          id="classroom-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          maxLength={40}
          placeholder="例如：机会成本与沉没成本"
          className="mt-1.5 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
        />

        <p className="mt-4 text-xs font-medium text-muted-foreground">选择参与者（1–3 个）</p>
        <div className="mt-2 space-y-1.5">
          {agents.map((agent) => {
            const isSelected = selected.includes(agent.id)
            return (
              <button
                key={agent.id}
                type="button"
                onClick={() => toggle(agent.id)}
                className={cn(
                  'flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition-colors',
                  isSelected
                    ? 'border-primary/35 bg-primary-soft/60'
                    : 'border-border bg-card hover:bg-muted/50',
                )}
              >
                <AgentAvatar agent={agent} size="sm" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-medium">{agent.name}</span>
                    <span className="rounded-full border border-border bg-card px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {agent.role_label}
                    </span>
                  </div>
                  <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                    {agent.short_description}
                  </p>
                </div>
                <span
                  className={cn(
                    'flex h-5 w-5 shrink-0 items-center justify-center rounded-md border',
                    isSelected
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'border-border bg-card text-transparent',
                  )}
                >
                  <Check className="h-3 w-3" />
                </span>
              </button>
            )
          })}
        </div>

        {error ? <p className="mt-3 text-[11px] text-red-600">{error}</p> : null}

        <div className="mt-5 flex items-center justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button size="sm" onClick={() => void create()} disabled={submitting || selected.length === 0}>
            {submitting ? '创建中…' : '创建课堂'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
