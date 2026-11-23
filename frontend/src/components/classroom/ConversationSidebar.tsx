import { MessagesSquare, Plus, Trash } from 'lucide-react'
import { useClassroomStore } from '../../store/classroom'
import { formatRelative } from '../../lib/format'
import { cn } from '../../lib/utils'
import { AgentAvatar } from './AgentAvatar'
import { Button } from '../ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/dialog'

export function ConversationSidebar({
  open,
  onOpenChange,
  onNewConversation,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onNewConversation: () => void
}) {
  const conversations = useClassroomStore((state) => state.conversations)
  const agents = useClassroomStore((state) => state.agents)
  const activeConversation = useClassroomStore((state) => state.activeConversation)
  const openConversation = useClassroomStore((state) => state.openConversation)
  const removeConversation = useClassroomStore((state) => state.removeConversation)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="right-0 top-0 h-full w-[360px] max-w-[92vw] border-l p-0 shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div>
            <DialogTitle className="flex items-center gap-2 text-sm">
              <MessagesSquare className="h-4 w-4 text-primary" />
              对话历史
            </DialogTitle>
            <DialogDescription className="mt-1">
              共 {conversations.length} 个课堂对话
            </DialogDescription>
          </div>
          <Button size="sm" variant="outline" onClick={onNewConversation}>
            <Plus className="h-3.5 w-3.5" />
            新建
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto scrollbar-thin p-3">
          {conversations.length === 0 ? (
            <p className="mt-10 text-center text-xs text-muted-foreground">还没有对话记录</p>
          ) : (
            <ul className="space-y-1.5">
              {conversations.map((conversation) => {
                const isActive = conversation.id === activeConversation?.id
                const members = agents.filter((agent) =>
                  conversation.selected_agent_ids.includes(agent.id),
                )
                return (
                  <li key={conversation.id}>
                    <div
                      className={cn(
                        'group flex items-start gap-2 rounded-lg border px-3 py-2.5 transition-colors',
                        isActive
                          ? 'border-primary/35 bg-primary-soft/60'
                          : 'border-transparent hover:border-border hover:bg-muted/60',
                      )}
                    >
                      <button
                        type="button"
                        className="min-w-0 flex-1 text-left"
                        onClick={() => {
                          void openConversation(conversation.id)
                          onOpenChange(false)
                        }}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-xs font-medium">{conversation.title}</span>
                          <span className="shrink-0 text-[10px] text-muted-foreground">
                            {formatRelative(conversation.updated_at)}
                          </span>
                        </div>
                        <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">
                          {conversation.last_message ?? '暂无提问'}
                        </p>
                        <div className="mt-1.5 flex items-center gap-1">
                          <div className="flex -space-x-1">
                            {members.map((agent) => (
                              <AgentAvatar key={agent.id} agent={agent} size="xs" />
                            ))}
                          </div>
                          <span className="text-[10px] text-muted-foreground">
                            {members.map((agent) => agent.name).join(' · ')}
                          </span>
                        </div>
                      </button>
                      <button
                        type="button"
                        title="删除对话"
                        onClick={() => {
                          if (window.confirm(`删除对话「${conversation.title}」？此操作不可恢复。`)) {
                            void removeConversation(conversation.id)
                          }
                        }}
                        className="mt-0.5 shrink-0 rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-red-50 hover:text-red-600 group-hover:opacity-100"
                      >
                        <Trash className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
