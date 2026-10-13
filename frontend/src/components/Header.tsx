import { cn } from '@/utils/helpers'
import { Button } from '@/components/ui/Button'
import { TerminalSquare, MessageSquare, LogOut } from 'lucide-react'

interface HeaderProps {
  onNewChat: () => void
  username?: string | null
  onLogout?: () => void
  className?: string
}

export const Header = ({ onNewChat, username, onLogout, className }: HeaderProps) => {
  const initials = username ? username.slice(0, 2).toUpperCase() : 'ET'

  return (
    <header
      className={cn(
        'h-16 bg-eternix-950/80 backdrop-blur-md border-b border-eternix-800 flex items-center justify-between px-4',
        className,
      )}
    >
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-eternix-500 to-eternix-700 flex items-center justify-center">
          <TerminalSquare className="w-5 h-5 text-white" />
        </div>
        <span className="font-semibold text-eternix-100">Eternix</span>
      </div>

      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onNewChat} aria-label="New chat">
          <MessageSquare className="w-4 h-4" />
          <span className="hidden sm:inline">New Chat</span>
        </Button>

        <div className="flex items-center gap-2 pl-3 ml-1 border-l border-eternix-800">
          <div
            className="w-8 h-8 rounded-full bg-eternix-700 flex items-center justify-center text-xs font-medium text-eternix-100"
            aria-hidden="true"
          >
            {initials}
          </div>
          <span className="hidden sm:inline text-sm text-eternix-200 max-w-[120px] truncate">
            {username ?? 'Account'}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={onLogout}
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut className="w-4 h-4" />
          </Button>
        </div>
      </div>
    </header>
  )
}
