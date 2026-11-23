import { useEffect, useRef, useState } from 'react'
import { CircleExclamationPoint, RotateCcw, SendHorizontal, Square, X } from 'lucide-react'
import { useClassroomStore, selectIsRunning } from '../../store/classroom'
import { cn } from '../../lib/utils'
import { AgentAvatar } from './AgentAvatar'
import { Button } from '../ui/button'

export function QuestionInput() {
  const [value, setValue] = useState('')
  const composingRef = useRef(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const agents = useClassroomStore((state) => state.agents)
  const selectedAgentIds = useClassroomStore((state) => state.selectedAgentIds)
  const activeConversation = useClassroomStore((state) => state.activeConversation)
  const task = useClassroomStore((state) => state.task)
  const submitting = useClassroomStore((state) => state.submitting)
  const error = useClassroomStore((state) => state.error)
  const clearError = useClassroomStore((state) => state.clearError)
  const sendMessage = useClassroomStore((state) => state.sendMessage)
  const stopGeneration = useClassroomStore((state) => state.stopGeneration)
  const resumeGeneration = useClassroomStore((state) => state.resumeGeneration)
  const isRunning = useClassroomStore(selectIsRunning)

  const participants = agents.filter((agent) => selectedAgentIds.includes(agent.id))
  const canSend = !!activeConversation && participants.length > 0 && !isRunning && !!value.trim()
  const canResume = !!task && (task.status === 'stopped' || task.status === 'failed')

  useEffect(() => {
    const element = textareaRef.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 160)}px`
  }, [value])

  const submit = () => {
    const text = value.trim()
    if (!text || !canSend) return
    setValue('')
    void sendMessage(text)
  }

  return (
    <div className="shrink-0 border-t border-border bg-card/85 px-3 pb-3 pt-2 sm:px-5">
      <div className="mx-auto w-full max-w-3xl">
        {error ? (
          <div className="mb-2 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-2.5 py-1.5 text-[11px] text-red-700">
            <CircleExclamationPoint className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="flex-1 leading-relaxed">{error}</span>
            <button
              type="button"
              onClick={clearError}
              className="shrink-0 rounded p-0.5 hover:bg-red-100"
              aria-label="关闭错误提示"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ) : null}

        <div className="mb-1.5 flex min-h-[22px] flex-wrap items-center gap-1.5">
          {activeConversation ? (
            participants.length > 0 ? (
              <>
                <span className="text-[11px] text-muted-foreground">本轮参与者</span>
                {participants.map((agent) => (
                  <span
                    key={agent.id}
                    className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/50 py-0.5 pl-0.5 pr-2 text-[11px]"
                  >
                    <AgentAvatar agent={agent} size="xs" />
                    <span className="font-medium">{agent.name}</span>
                    <span className="text-muted-foreground">{agent.role_label}</span>
                  </span>
                ))}
              </>
            ) : (
              <span className="text-[11px] text-red-600">至少选择 1 个 Agent 才能提交问题</span>
            )
          ) : (
            <span className="text-[11px] text-muted-foreground">请先新建课堂并选择参与者</span>
          )}
        </div>

        <div
          className={cn(
            'flex items-end gap-2 rounded-xl border bg-card px-3 py-2 transition-shadow',
            'border-border focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/10',
          )}
        >
          <textarea
            ref={textareaRef}
            value={value}
            rows={1}
            placeholder={
              activeConversation
                ? isRunning
                  ? '课堂讨论进行中，可等待完成或停止生成…'
                  : '输入你的问题，Enter 发送，Shift + Enter 换行'
                : '请先新建课堂'
            }
            disabled={!activeConversation || isRunning}
            onChange={(event) => setValue(event.target.value)}
            onCompositionStart={() => {
              composingRef.current = true
            }}
            onCompositionEnd={() => {
              composingRef.current = false
            }}
            onKeyDown={(event) => {
              if (event.key !== 'Enter' || event.shiftKey) return
              if (composingRef.current || event.nativeEvent.isComposing) return
              event.preventDefault()
              submit()
            }}
            className="max-h-40 min-h-[44px] flex-1 resize-none bg-transparent py-1.5 text-sm leading-relaxed outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
          />

          <div className="flex shrink-0 items-center gap-1.5 pb-0.5">
            {canResume && !isRunning ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => void resumeGeneration()}
                disabled={submitting}
                title="从上次中断处继续执行"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                继续生成
              </Button>
            ) : null}

            {isRunning ? (
              <Button
                variant="outline"
                size="sm"
                className="border-amber-200 text-amber-700 hover:bg-amber-50"
                onClick={() => void stopGeneration()}
              >
                <Square className="h-3.5 w-3.5 fill-current" />
                停止生成
              </Button>
            ) : (
              <Button size="sm" onClick={submit} disabled={!canSend} title="发送问题">
                <SendHorizontal className="h-3.5 w-3.5" />
                发送
              </Button>
            )}
          </div>
        </div>

        <div className="mt-1.5 flex items-center justify-between text-[10px] text-muted-foreground">
          <span>Enter 发送 · Shift + Enter 换行 · 支持 Markdown 与 LaTeX 公式</span>
          <span>{value.length}/8000</span>
        </div>
      </div>
    </div>
  )
}
