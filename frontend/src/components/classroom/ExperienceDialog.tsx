import { useCallback, useEffect, useState } from 'react'
import { Check, Loader2, X } from 'lucide-react'
import { api } from '../../services/api'
import { useClassroomStore } from '../../store/classroom'
import type { AgentExperience, ExperienceList } from '../../types/classroom'
import { cn } from '../../lib/utils'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/dialog'

const TYPE_LABELS: Record<string, string> = {
  task_result: '任务结果',
  tool_usage: '工具使用',
  user_feedback: '用户反馈',
  collaboration: '协作策略',
  knowledge_correction: '知识修正',
}

const STATUS_META: Record<
  string,
  { label: string; variant: 'success' | 'warning' | 'danger' | 'outline' }
> = {
  validated: { label: '已验证', variant: 'success' },
  candidate: { label: '待验证', variant: 'warning' },
  rejected: { label: '已驳回', variant: 'danger' },
}

const FILTERS = [
  { value: '', label: '全部' },
  { value: 'validated', label: '已验证' },
  { value: 'candidate', label: '待验证' },
  { value: 'rejected', label: '已驳回' },
]

export function ExperienceDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const agents = useClassroomStore((state) => state.agents)
  const [agentId, setAgentId] = useState('')
  const [status, setStatus] = useState('')
  const [data, setData] = useState<ExperienceList | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reviewing, setReviewing] = useState<string | null>(null)

  const selectedAgent = agentId || agents[0]?.id || ''

  const load = useCallback(async (targetAgent: string, targetStatus: string) => {
    if (!targetAgent) return
    setLoading(true)
    setError(null)
    try {
      const result = await api.listExperiences(targetAgent, targetStatus || undefined)
      setData(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取经验失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    if (!agentId && agents.length > 0) {
      setAgentId(agents[0].id)
      return
    }
    void load(selectedAgent, status)
  }, [open, agentId, status, agents, load, selectedAgent])

  const review = async (item: AgentExperience, next: 'validated' | 'rejected') => {
    setReviewing(item.id)
    setError(null)
    try {
      await api.reviewExperience(item.agent_id, item.id, next, '课堂内人工复核')
      await load(selectedAgent, status)
    } catch (err) {
      setError(err instanceof Error ? err.message : '复核失败')
    } finally {
      setReviewing(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="left-1/2 top-1/2 max-h-[86vh] w-[calc(100vw-2rem)] max-w-2xl -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-xl p-0 shadow-xl">
        <div className="border-b border-border px-5 py-4">
          <DialogTitle>Agent 经验库</DialogTitle>
          <DialogDescription className="mt-1">
            经验来自真实任务结果、工具执行、用户反馈与协作记录；只有通过验证的经验才会按相关度注入后续对话。
          </DialogDescription>
        </div>

        <div className="flex flex-wrap items-center gap-1.5 border-b border-border px-4 py-2.5">
          {agents.map((agent) => (
            <button
              key={agent.id}
              type="button"
              onClick={() => setAgentId(agent.id)}
              className={cn(
                'rounded-full border px-2.5 py-1 text-xs transition-colors',
                selectedAgent === agent.id
                  ? 'border-primary/30 bg-primary-soft font-medium text-primary'
                  : 'border-border text-muted-foreground hover:bg-muted',
              )}
            >
              {agent.name}
            </button>
          ))}
          <div className="ml-auto flex items-center gap-1">
            {FILTERS.map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => setStatus(item.value)}
                className={cn(
                  'rounded-md px-2 py-1 text-[11px] transition-colors',
                  status === item.value
                    ? 'bg-muted font-medium text-foreground'
                    : 'text-muted-foreground hover:bg-muted/60',
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4 scrollbar-thin">
          {data ? (
            <div className="mb-3 flex flex-wrap gap-1.5">
              <Badge variant="success">已验证 {data.counts.validated ?? 0}</Badge>
              <Badge variant="warning">待验证 {data.counts.candidate ?? 0}</Badge>
              <Badge variant="danger">已驳回 {data.counts.rejected ?? 0}</Badge>
              <Badge variant="outline">总计 {data.counts.total ?? 0}</Badge>
            </div>
          ) : null}

          {error ? <p className="mb-3 text-xs text-red-600">{error}</p> : null}
          {loading ? (
            <div className="flex items-center gap-2 py-8 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              正在读取经验…
            </div>
          ) : null}

          {!loading && data && data.experiences.length === 0 ? (
            <p className="py-10 text-center text-xs text-muted-foreground">
              暂无经验。完成多轮真实对话、使用工具或给出反馈后会自动提取候选经验。
            </p>
          ) : null}

          <div className="space-y-2.5">
            {!loading
              ? data?.experiences.map((item) => {
                  const statusMeta = STATUS_META[item.validation_status] ?? {
                    label: item.validation_status,
                    variant: 'outline' as const,
                  }
                  return (
                    <div
                      key={item.id}
                      className="rounded-lg border border-border bg-card px-3.5 py-3"
                    >
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge variant="outline">
                          {TYPE_LABELS[item.experience_type] ?? item.experience_type}
                        </Badge>
                        <Badge variant={statusMeta.variant}>{statusMeta.label}</Badge>
                        <span className="text-[11px] text-muted-foreground">
                          置信度 {Math.round(item.confidence * 100)}%
                        </span>
                        {item.use_count > 0 ? (
                          <span className="text-[11px] text-muted-foreground">
                            已使用 {item.use_count} 次
                          </span>
                        ) : null}
                        {item.validation_status === 'candidate' ? (
                          <span className="ml-auto flex items-center gap-1">
                            <Button
                              size="sm"
                              variant="secondary"
                              disabled={reviewing === item.id}
                              onClick={() => void review(item, 'validated')}
                            >
                              <Check className="h-3 w-3" />
                              通过
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={reviewing === item.id}
                              onClick={() => void review(item, 'rejected')}
                            >
                              <X className="h-3 w-3" />
                              驳回
                            </Button>
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-2 text-sm leading-relaxed">{item.content}</p>
                      {item.validation_note ? (
                        <p className="mt-1.5 text-[11px] text-muted-foreground">
                          验证说明：{item.validation_note}
                        </p>
                      ) : null}
                    </div>
                  )
                })
              : null}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
