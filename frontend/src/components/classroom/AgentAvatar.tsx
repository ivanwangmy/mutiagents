import { useState } from 'react'
import { cn } from '../../lib/utils'
import { hexAlpha, initialOf } from '../../lib/format'
import type { AgentSummary } from '../../types/classroom'

const SIZES = {
  xs: 22,
  sm: 28,
  md: 36,
  lg: 46,
  xl: 64,
} as const

export type AvatarSize = keyof typeof SIZES

export function AgentAvatar({
  agent,
  size = 'md',
  className,
  ring = true,
}: {
  agent: Pick<AgentSummary, 'name' | 'avatar' | 'theme_color'>
  size?: AvatarSize
  className?: string
  ring?: boolean
}) {
  const [failed, setFailed] = useState(false)
  const px = SIZES[size]

  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-white',
        ring && 'ring-2 ring-white',
        className,
      )}
      style={{
        width: px,
        height: px,
        backgroundColor: hexAlpha(agent.theme_color, 0.14),
        boxShadow: '0 0 0 1px rgba(15, 23, 42, 0.06)',
      }}
      title={agent.name}
    >
      {failed ? (
        <span
          className="font-semibold"
          style={{ color: agent.theme_color, fontSize: px * 0.42 }}
        >
          {initialOf(agent.name)}
        </span>
      ) : (
        <img
          src={agent.avatar}
          alt={agent.name}
          className="h-full w-full object-cover"
          onError={() => setFailed(true)}
        />
      )}
    </span>
  )
}
