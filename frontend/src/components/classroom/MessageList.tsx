import { useEffect, useRef } from 'react'
import { GraduationCap, Sparkles } from 'lucide-react'
import { useClassroomStore, selectIsRunning } from '../../store/classroom'
import { AgentAvatar } from './AgentAvatar'
import { MessageBubble } from './MessageBubble'
import { Button } from '../ui/button'

export function MessageList({ onNewConversation }: { onNewConversation: () => void }) {
  const agents = useClassroomStore((state) => state.agents)
  const messages = useClassroomStore((state) => state.messages)
  const selectedAgentIds = useClassroomStore((state) => state.selectedAgentIds)
  const activeConversation = useClassroomStore((state) => state.activeConversation)
  const messagesLoading = useClassroomStore((state) => state.messagesLoading)
  const task = useClassroomStore((state) => state.task)
  const isRunning = useClassroomStore(selectIsRunning)
  const bottomRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)

  const lastContent = messages.length > 0 ? messages[messages.length - 1].content : ''

  useEffect(() => {
    stickRef.current = true
  }, [activeConversation?.id])

  useEffect(() => {
    if (!stickRef.current) return
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages.length, lastContent, isRunning])

  const handleScroll = () => {
    const element = scrollRef.current
    if (!element) return
    stickRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 120
  }

  const participants = agents.filter((agent) => selectedAgentIds.includes(agent.id))

  if (!activeConversation) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-10">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary-soft text-primary">
          <GraduationCap className="h-7 w-7" />
        </div>
        <h2 className="mt-4 text-lg font-semibold">进入 AI 智播课堂</h2>
        <p className="mt-1.5 max-w-md text-center text-sm leading-relaxed text-muted-foreground">
          选择 Alex（教师）、Mia（助教）、Ethan（学生）中的一位或多位，开始一场真实的多智能体课堂讨论。
        </p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-4">
          {agents.map((agent) => (
            <div key={agent.id} className="flex w-24 flex-col items-center gap-1.5">
              <AgentAvatar agent={agent} size="xl" />
              <span className="text-xs font-medium">{agent.name}</span>
              <span className="text-[11px] text-muted-foreground">{agent.role_label}</span>
            </div>
          ))}
        </div>
        <Button className="mt-6" onClick={onNewConversation}>
          <Sparkles className="h-4 w-4" />
          新建课堂
        </Button>
      </div>
    )
  }

  if (messagesLoading) {
    return (
      <div className="flex-1 space-y-4 px-4 py-6 sm:px-6">
        {[0, 1, 2].map((index) => (
          <div key={index} className="flex gap-3">
            <div className="h-9 w-9 animate-pulse rounded-full bg-muted" />
            <div className="flex-1 space-y-2">
              <div className="h-3 w-24 animate-pulse rounded bg-muted" />
              <div className="h-16 animate-pulse rounded-xl bg-muted/70" />
            </div>
          </div>
        ))}
      </div>
    )
  }

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-10">
        <div className="flex -space-x-2">
          {participants.map((agent) => (
            <AgentAvatar key={agent.id} agent={agent} size="lg" />
          ))}
        </div>
        <h2 className="mt-4 text-base font-semibold">课堂已就绪</h2>
        <p className="mt-1.5 max-w-md text-center text-sm leading-relaxed text-muted-foreground">
          {participants.length > 0
            ? `${participants.map((agent) => agent.name).join('、')} 已加入课堂，在下方输入第一个问题开始讨论。`
            : '请先在右侧选择至少一位参与者。'}
        </p>
      </div>
    )
  }

  return (
    <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto scrollbar-thin">
      <div className="mx-auto w-full max-w-3xl space-y-5 px-4 py-6 sm:px-6">
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} agents={agents} />
        ))}

        {isRunning ? (
          <div className="flex items-center gap-2.5">
            <div className="flex -space-x-1.5">
              {agents
                .filter((agent) => (task?.participating_agent_ids ?? selectedAgentIds).includes(agent.id))
                .map((agent) => (
                  <AgentAvatar key={agent.id} agent={agent} size="md" />
                ))}
            </div>
            <div className="flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5">
              <span className="flex gap-0.5">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:150ms]" />
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:300ms]" />
              </span>
              <span className="text-[11px] text-muted-foreground">课堂讨论进行中…</span>
            </div>
          </div>
        ) : null}

        <div ref={bottomRef} />
      </div>
    </div>
  )
}
