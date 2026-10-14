import { useState, useRef, useEffect } from 'react'
import { cn } from '@/utils/helpers'
import { Button } from '@/components/ui/Button'
import { TerminalSquare, MessageSquare, LogOut, ChevronDown, LayoutDashboard, Wifi, WifiOff, User } from 'lucide-react'

interface HeaderProps {
  onNewChat: () => void
  username?: string | null
  onLogout?: () => void
  onSidebarToggle?: () => void
  isSidebarCollapsed?: boolean
  className?: string
}

export const Header = ({ 
  onNewChat, 
  username, 
  onLogout, 
  onSidebarToggle,
  isSidebarCollapsed,
  className 
}: HeaderProps) => {
  const [isAccountMenuOpen, setIsAccountMenuOpen] = useState(false)
  const accountMenuRef = useRef<HTMLDivElement>(null)
  const initials = username ? username.slice(0, 2).toUpperCase() : 'ET'

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (accountMenuRef.current && !accountMenuRef.current.contains(event.target as Node)) {
        setIsAccountMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <header
      className={cn(
        'h-16 bg-eternix-950/80 backdrop-blur-md border-b border-eternix-800 flex items-center justify-between px-4',
        className,
      )}
    >
      <div className="flex items-center gap-3 min-w-0">
        <button
          onClick={onSidebarToggle}
          className={cn(
            'w-8 h-8 rounded-lg flex items-center justify-center transition-colors',
            'bg-eternix-800/50 text-eternix-300 hover:bg-eternix-700 hover:text-eternix-100',
            isSidebarCollapsed && 'rotate-180'
          )}
          aria-label={isSidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!isSidebarCollapsed}
        >
          <LayoutDashboard className="w-5 h-5" />
        </button>
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-eternix-purple-500 to-eternix-purple-700 flex items-center justify-center">
            <TerminalSquare className="w-5 h-5 text-white" />
          </div>
          <span className="font-bold text-eternix-100 text-lg">ETERNIX</span>
          <span className="text-xs font-medium px-2 py-0.5 rounded bg-eternix-gold-500/20 text-eternix-gold-400 border border-eternix-gold-500/30">V.2</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onNewChat} aria-label="New chat">
          <MessageSquare className="w-4 h-4" />
          <span className="hidden sm:inline">New Chat</span>
        </Button>

        {/* Connection status indicator */}
        <div className="hidden md:flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-eternix-800/50 border border-eternix-700/50">
          <Wifi className="w-3.5 h-3.5 text-eternix-purple-400" />
          <span className="text-xs text-eternix-300 font-medium">Connected</span>
        </div>

        <div className="flex items-center gap-2 pl-3 ml-1 border-l border-eternix-800" ref={accountMenuRef}>
          <div
            className="w-8 h-8 rounded-full bg-eternix-purple-600/30 flex items-center justify-center text-xs font-medium text-eternix-100 border border-eternix-purple-500/30 cursor-pointer"
            onClick={() => setIsAccountMenuOpen(!isAccountMenuOpen)}
            aria-label="Account menu"
            aria-expanded={isAccountMenuOpen}
            aria-haspopup="true"
          >
            {initials}
          </div>
          <span className="hidden sm:inline text-sm text-eternix-200 max-w-[120px] truncate cursor-pointer" onClick={() => setIsAccountMenuOpen(!isAccountMenuOpen)}>
            {username ?? 'Account'}
          </span>
          <ChevronDown 
            className={cn('w-3.5 h-3.5 text-eternix-400 transition-transform', isAccountMenuOpen && 'rotate-180')} 
            aria-hidden="true"
          />

          {isAccountMenuOpen && (
            <div className="absolute right-0 top-full mt-2 w-56 card-elevated shadow-xl animate-fade-in" role="menu">
              <div className="px-4 py-3 border-b border-eternix-800">
                <p className="text-sm font-medium text-eternix-100">{username ?? 'Account'}</p>
                <p className="text-xs text-eternix-500 truncate">eternix.local</p>
              </div>
              <button
                role="menuitem"
                className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-eternix-300 hover:text-eternix-100 hover:bg-eternix-800/50 transition-colors"
                onClick={() => { setIsAccountMenuOpen(false); /* TODO: navigate to profile */ }}
              >
                <User className="w-4 h-4" />
                Profile
              </button>
              <button
                role="menuitem"
                className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-eternix-300 hover:text-eternix-100 hover:bg-eternix-800/50 transition-colors"
                onClick={() => { setIsAccountMenuOpen(false); /* TODO: navigate to payment */ }}
              >
                <TerminalSquare className="w-4 h-4" />
                Manage Payment
              </button>
              <hr className="border-eternix-800 my-1" />
              <button
                role="menuitem"
                className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-red-400 hover:text-red-300 hover:bg-red-500/10 transition-colors"
                onClick={() => { setIsAccountMenuOpen(false); onLogout?.() }}
              >
                <LogOut className="w-4 h-4" />
                Sign Out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
