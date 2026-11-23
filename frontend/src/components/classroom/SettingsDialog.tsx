import { useEffect, useState } from 'react'
import { api } from '../../services/api'
import type { ConfigStatus, HealthResponse, SystemInfo } from '../../types/system'
import { Badge } from '../ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/dialog'

const LIMIT_LABELS: Record<string, string> = {
  max_output_tokens: '单次输出上限',
  max_context_tokens: '上下文预算',
  task_token_budget: '任务 Token 预算',
  task_max_model_calls: '任务模型调用上限',
  task_max_messages: '任务消息上限',
  task_max_turns: '任务轮次上限',
  task_max_seconds: '任务时长上限（秒）',
  memory_retrieval_limit: '记忆检索条数',
}

export function SettingsDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [config, setConfig] = useState<ConfigStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([api.health(), api.systemInfo(), api.configStatus()])
      .then(([healthData, infoData, configData]) => {
        if (cancelled) return
        setHealth(healthData)
        setInfo(infoData)
        setConfig(configData)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : '无法读取系统配置')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="left-1/2 top-1/2 max-h-[86vh] w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl p-6 shadow-xl scrollbar-thin">
        <DialogTitle>设置</DialogTitle>
        <DialogDescription className="mt-1">
          以下信息全部来自后端真实配置，密钥不会返回前端。
        </DialogDescription>

        {loading ? <p className="mt-6 text-xs text-muted-foreground">正在读取系统状态…</p> : null}
        {error ? <p className="mt-6 text-xs text-red-600">{error}</p> : null}

        {!loading && !error ? (
          <div className="mt-5 space-y-5">
            <section>
              <h4 className="text-xs font-semibold text-muted-foreground">服务状态</h4>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-lg border border-border bg-muted/40 px-3 py-2">
                  <p className="text-muted-foreground">后端</p>
                  <p className="mt-0.5 font-medium">{health?.status ?? '-'}</p>
                </div>
                <div className="rounded-lg border border-border bg-muted/40 px-3 py-2">
                  <p className="text-muted-foreground">数据库</p>
                  <p className="mt-0.5 font-medium">{health?.database ?? '-'}</p>
                </div>
                <div className="rounded-lg border border-border bg-muted/40 px-3 py-2">
                  <p className="text-muted-foreground">模型密钥</p>
                  <p className="mt-0.5 font-medium">
                    {health?.model_configured || config?.model_configured ? '已配置' : '未配置'}
                  </p>
                </div>
                <div className="rounded-lg border border-border bg-muted/40 px-3 py-2">
                  <p className="text-muted-foreground">版本</p>
                  <p className="mt-0.5 font-medium">{health?.version ?? '-'}</p>
                </div>
              </div>
            </section>

            <section>
              <h4 className="text-xs font-semibold text-muted-foreground">模型能力</h4>
              <div className="mt-2 rounded-lg border border-border px-3 py-2 text-xs">
                <p>
                  模型：<span className="font-medium">{config?.model_name ?? '-'}</span>
                </p>
                <p className="mt-0.5 text-muted-foreground">供应商：{config?.provider ?? '-'}</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {config
                    ? Object.entries(config.capabilities).map(([key, value]) => (
                        <Badge key={key} variant={value === true ? 'success' : 'outline'}>
                          {key}：{value === true ? '可用' : value === false ? '不可用' : String(value)}
                        </Badge>
                      ))
                    : null}
                </div>
              </div>
            </section>

            <section>
              <h4 className="text-xs font-semibold text-muted-foreground">运行环境</h4>
              <div className="mt-2 space-y-1 rounded-lg border border-border px-3 py-2 text-xs text-muted-foreground">
                <p>Python：{info?.python_version ?? '-'}</p>
                <p>平台：{info?.platform ?? '-'}</p>
                <p>数据库后端：{info?.database_backend ?? '-'}</p>
                <p>检查点后端：{info?.checkpointer_backend ?? '-'}</p>
                <p>Agent 数量：{info?.agent_count ?? 0}</p>
              </div>
            </section>

            <section>
              <h4 className="text-xs font-semibold text-muted-foreground">预算限制</h4>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                {info
                  ? Object.entries(info.limits).map(([key, value]) => (
                      <div key={key} className="rounded-lg border border-border bg-muted/40 px-3 py-2">
                        <p className="text-muted-foreground">{LIMIT_LABELS[key] ?? key}</p>
                        <p className="mt-0.5 font-medium">{value}</p>
                      </div>
                    ))
                  : null}
              </div>
            </section>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
