import { useState } from 'react'
import { Loader2, ThumbsDown, ThumbsUp } from 'lucide-react'
import { api } from '../../services/api'
import type { ChatMessage } from '../../types/classroom'
import { cn } from '../../lib/utils'

export function MessageFeedback({ message }: { message: ChatMessage }) {
  const [sent, setSent] = useState<{ rating: number; experience: string | null } | null>(
    null,
  )
  const [showComment, setShowComment] = useState(false)
  const [comment, setComment] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!message.sender_agent_id) return null

  const submit = async (rating: number, text: string) => {
    if (pending) return
    setPending(true)
    setError(null)
    try {
      const result = await api.submitFeedback(message.conversation_id, {
        message_id: message.id,
        agent_id: message.sender_agent_id ?? undefined,
        rating,
        comment: text.trim(),
      })
      setSent({
        rating,
        experience: result.experience ? result.experience.validation_status : null,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : '反馈提交失败')
    } finally {
      setPending(false)
    }
  }

  if (sent) {
    const statusLabel =
      sent.experience === 'validated'
        ? '，已通过验证并可能用于后续相似任务'
        : sent.experience === 'candidate'
          ? '，已作为待验证经验记录'
          : ''
    return (
      <p className="mt-2 text-[11px] text-emerald-700">
        已记录{sent.rating > 0 ? '肯定' : '改进'}反馈{statusLabel}
      </p>
    )
  }

  return (
    <div className="mt-2 border-t border-border/70 pt-2">
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] text-muted-foreground">这条回答对你有帮助吗？</span>
        <button
          type="button"
          disabled={pending}
          onClick={() => void submit(1, '')}
          className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-emerald-50 hover:text-emerald-700 disabled:opacity-50"
          title="有帮助"
        >
          <ThumbsUp className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          disabled={pending}
          onClick={() => setShowComment((value) => !value)}
          className={cn(
            'rounded-md p-1 transition-colors disabled:opacity-50',
            showComment
              ? 'bg-red-50 text-red-600'
              : 'text-muted-foreground hover:bg-red-50 hover:text-red-600',
          )}
          title="需要改进"
        >
          <ThumbsDown className="h-3.5 w-3.5" />
        </button>
        {pending ? (
          <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
        ) : null}
      </div>

      {showComment ? (
        <div className="mt-2 flex items-start gap-1.5">
          <input
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={300}
            placeholder="请指出问题或希望改进的地方，将用于经验提取"
            className="h-8 min-w-0 flex-1 rounded-md border border-border bg-card px-2 text-xs outline-none focus:border-primary/40"
          />
          <button
            type="button"
            disabled={pending || comment.trim().length === 0}
            onClick={() => void submit(-1, comment)}
            className="h-8 shrink-0 rounded-md bg-primary px-2.5 text-xs text-primary-foreground disabled:opacity-50"
          >
            提交
          </button>
        </div>
      ) : null}

      {error ? <p className="mt-1 text-[11px] text-red-600">{error}</p> : null}
    </div>
  )
}
