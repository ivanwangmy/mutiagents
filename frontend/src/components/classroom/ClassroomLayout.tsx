import { useEffect, useState } from 'react'
import { CircleExclamationPoint, X } from 'lucide-react'
import { useClassroomStore } from '../../store/classroom'
import { Dialog, DialogContent, DialogTitle } from '../ui/dialog'
import { AgentSelector } from './AgentSelector'
import { AgentStatusPanel } from './AgentStatusPanel'
import { ConversationSidebar } from './ConversationSidebar'
import { DiscussionPanel } from './DiscussionPanel'
import { ExperienceDialog } from './ExperienceDialog'
import { NewConversationDialog } from './NewConversationDialog'
import { SettingsDialog } from './SettingsDialog'
import { TopNavigation } from './TopNavigation'

export function ClassroomLayout() {
  const bootstrap = useClassroomStore((state) => state.bootstrap)
  const error = useClassroomStore((state) => state.error)
  const clearError = useClassroomStore((state) => state.clearError)
  const activeConversation = useClassroomStore((state) => state.activeConversation)
  const connection = useClassroomStore((state) => state.connection)

  const [historyOpen, setHistoryOpen] = useState(false)
  const [newOpen, setNewOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [agentsOpen, setAgentsOpen] = useState(false)
  const [experiencesOpen, setExperiencesOpen] = useState(false)

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  const openNewConversation = () => {
    setHistoryOpen(false)
    setAgentsOpen(false)
    setNewOpen(true)
  }

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-background">
      <TopNavigation
        onNewConversation={openNewConversation}
        onOpenHistory={() => setHistoryOpen(true)}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenAgents={() => setAgentsOpen(true)}
        onOpenExperiences={() => setExperiencesOpen(true)}
      />

      {error && !activeConversation ? (
        <div className="flex items-center gap-2 border-b border-red-200 bg-red-50 px-4 py-2 text-xs text-red-700">
          <CircleExclamationPoint className="h-3.5 w-3.5 shrink-0" />
          <span className="flex-1">{error}</span>
          <button
            type="button"
            onClick={clearError}
            className="rounded p-0.5 hover:bg-red-100"
            aria-label="关闭错误提示"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : null}

      {connection === 'reconnecting' ? (
        <div className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-1.5 text-xs text-amber-700">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
          实时连接中断，正在自动重连并补拉遗漏事件…
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1">
        <DiscussionPanel onNewConversation={openNewConversation} />

        <aside className="hidden shrink-0 flex-col border-l border-border bg-muted/25 md:flex md:w-[276px] lg:w-[300px] xl:w-[340px]">
          <div className="flex-1 space-y-3 overflow-y-auto scrollbar-thin p-3">
            <AgentStatusPanel />
            <AgentSelector />
          </div>
        </aside>
      </div>

      <ConversationSidebar
        open={historyOpen}
        onOpenChange={setHistoryOpen}
        onNewConversation={openNewConversation}
      />
      <NewConversationDialog open={newOpen} onOpenChange={setNewOpen} />
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
      <ExperienceDialog open={experiencesOpen} onOpenChange={setExperiencesOpen} />

      <Dialog open={agentsOpen} onOpenChange={setAgentsOpen}>
        <DialogContent className="right-0 top-0 h-full w-[330px] max-w-[90vw] border-l p-0 shadow-xl">
          <div className="border-b border-border px-4 py-3">
            <DialogTitle className="text-sm">课堂参与者</DialogTitle>
          </div>
          <div className="flex-1 space-y-3 overflow-y-auto scrollbar-thin p-3">
            <AgentStatusPanel />
            <AgentSelector />
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
