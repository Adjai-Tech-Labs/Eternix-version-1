import { cn } from '@/utils/helpers'

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'default' | 'success' | 'warning' | 'error' | 'info' | 'neutral' | 'gold'
  size?: 'sm' | 'md'
  dot?: boolean
}

export const Badge = ({ className, variant = 'default', size = 'md', dot, children, ...props }: BadgeProps) => {
  const variants = {
    default: 'bg-eternix-700 text-eternix-200 border-eternix-600',
    success: 'bg-green-500/20 text-green-400 border-green-500/30',
    warning: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    error: 'bg-red-500/20 text-red-400 border-red-500/30',
    info: 'bg-eternix-lightBlue-500/20 text-eternix-lightBlue-400 border-eternix-lightBlue-500/30',
    neutral: 'bg-eternix-600 text-eternix-300 border-eternix-500/30',
    gold: 'bg-eternix-gold-500/20 text-eternix-gold-400 border-eternix-gold-500/30',
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