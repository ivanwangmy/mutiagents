import { useClassroomStore } from '../../store/classroom'
import { AgentAvatar } from './AgentAvatar'
import { MessageList } from './MessageList'
import { QuestionInput } from './QuestionInput'

export function DiscussionPanel({ onNewConversation }: { onNewConversation: () => void }) {
  const agents = useClassroomStore((state) => state.agents)
  const activeConversation = useClassroomStore((state) => state.activeConversation)
  const selectedAgentIds = useClassroomStore((state) => state.selectedAgentIds)

  const participants = agents.filter((agent) => selectedAgentIds.includes(agent.id))

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col bg-background">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border bg-background/80 px-4 py-2.5 sm:px-6">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">课堂讨论舞台</h2>
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
            {activeConversation
              ? `${activeConversation.title} · ${participants.length} 位参与者`
              : '选择参与者后开始课堂'}
          </p>
        </div>
        <div className="flex shrink-0 -space-x-1.5">
          {participants.map((agent) => (
            <AgentAvatar key={agent.id} agent={agent} size="sm" />
          ))}
        </div>
      </div>

      <MessageList onNewConversation={onNewConversation} />
      <QuestionInput />
    </section>
  )
}
