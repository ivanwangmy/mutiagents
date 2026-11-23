import { Brain, GraduationCap, MessagesSquare, Plus, Settings, Users } from 'lucide-react'
import { useClassroomStore } from '../../store/classroom'
import { cn } from '../../lib/utils'
import { Button } from '../ui/button'

function statusView(status: string | undefined, submitting: boolean) {
  if (submitting) return { label: '提交中', dot: 'bg-amber-500', text: 'text-amber-700' }
  switch (status) {
    case 'pending':
    case 'running':
      return { label: '讨论进行中', dot: 'bg-emerald-500', text: 'text-emerald-700' }
    case 'completed':
      return { label: '已完成', dot: 'bg-slate-400', text: 'text-muted-foreground' }
    case 'stopped':
      return { label: '已停止', dot: 'bg-amber-500', text: 'text-amber-700' }
    case 'failed':
      return { label: '失败', dot: 'bg-red-500', text: 'text-red-700' }
    default:
      return { label: '待提问', dot: 'bg-slate-300', text: 'text-muted-foreground' }
  }
}

export function TopNavigation({
  onNewConversation,
  onOpenHistory,
  onOpenSettings,
  onOpenAgents,
  onOpenExperiences,
}: {
  onNewConversation: () => void
  onOpenHistory: () => void
  onOpenSettings: () => void
  onOpenAgents: () => void
  onOpenExperiences: () => void
}) {
  const activeConversation = useClassroomStore((state) => state.activeConversation)
  const task = useClassroomStore((state) => state.task)
  const submitting = useClassroomStore((state) => state.submitting)
  const status = statusView(task?.status, submitting)

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-card px-3 sm:px-5">
      <div className="flex min-w-0 items-center gap-2.5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-soft text-primary">
          <GraduationCap className="h-[18px] w-[18px]" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold leading-tight">AI 智播课堂</p>
          <p className="hidden truncate text-[11px] leading-tight text-muted-foreground sm:block">
            多智能体教学互动平台
          </p>
        </div>
      </div>

      <div className="hidden min-w-0 flex-1 justify-center md:flex">
        {activeConversation ? (
          <div className="flex max-w-[420px] items-center gap-2 rounded-full border border-border bg-muted/60 px-3 py-1.5">
            <span className={cn('h-1.5 w-1.5 rounded-full', status.dot)} />
            <span className="truncate text-xs font-medium">{activeConversation.title}</span>
            <span className={cn('hidden text-[11px] lg:inline', status.text)}>{status.label}</span>
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">尚未开始课堂</span>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        <Button variant="default" size="sm" onClick={onNewConversation}>
          <Plus className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">新建对话</span>
        </Button>
        <Button variant="ghost" size="sm" onClick={onOpenHistory}>
          <MessagesSquare className="h-4 w-4" />
          <span className="hidden lg:inline">对话历史</span>
        </Button>
        <Button variant="ghost" size="sm" onClick={onOpenExperiences}>
          <Brain className="h-4 w-4" />
          <span className="hidden lg:inline">经验库</span>
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          onClick={onOpenAgents}
          title="课堂参与者"
        >
          <Users className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" onClick={onOpenSettings} title="设置">
          <Settings className="h-4 w-4" />
        </Button>
      </div>
    </header>
  )
}
