import { forwardRef } from 'react'
import { cn } from '@/utils/helpers'

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'gold'
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', loading, disabled, children, ...props }, ref) => {
    const baseStyles = 'inline-flex items-center justify-center gap-2 font-medium rounded-lg transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-eternix-purple-500 focus-visible:ring-offset-2 focus-visible:ring-offset-eternix-950 disabled:opacity-50 disabled:cursor-not-allowed'
    
    const variants = {
      primary: 'bg-eternix-purple-600 text-white hover:bg-eternix-purple-500 active:bg-eternix-purple-700',
      secondary: 'bg-eternix-800 text-eternix-100 hover:bg-eternix-700 active:bg-eternix-600 border border-eternix-700',
      ghost: 'bg-transparent text-eternix-300 hover:bg-eternix-800 active:bg-eternix-700',
      danger: 'bg-red-600/20 text-red-400 hover:bg-red-600/30 active:bg-red-600/40 border border-red-600/30',
      gold: 'bg-eternix-gold-500 text-eternix-950 hover:bg-eternix-gold-400 active:bg-eternix-gold-600 font-semibold',
    }

    const sizes = {
      sm: 'px-3 py-1.5 text-sm',
      md: 'px-4 py-2 text-base',
      lg: 'px-6 py-3 text-lg',
    }

    return (
      <button
        ref={ref}
        className={cn(baseStyles, variants[variant], sizes[size], className)}
        disabled={disabled || loading}
        {...props}
      >
        {loading && (
          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
        )}
        {children}
      </button>
    )
  }
)

Button.displayName = 'Button'