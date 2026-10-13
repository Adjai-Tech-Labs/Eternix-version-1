import { cn } from '@/utils/helpers'

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'default' | 'success' | 'warning' | 'error' | 'info' | 'neutral'
  size?: 'sm' | 'md'
  dot?: boolean
}

export const Badge = ({ className, variant = 'default', size = 'md', dot, children, ...props }: BadgeProps) => {
  const variants = {
    default: 'bg-eternix-700 text-eternix-200 border-eternix-600',
    success: 'bg-green-500/20 text-green-400 border-green-500/30',
    warning: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    error: 'bg-red-500/20 text-red-400 border-red-500/30',
    info: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    neutral: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
  }

  const sizes = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-2.5 py-1 text-sm',
  }

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border font-medium',
        variants[variant],
        sizes[size],
        className
      )}
      {...props}
    >
      {dot && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse-soft" />}
      {children}
    </span>
  )
}