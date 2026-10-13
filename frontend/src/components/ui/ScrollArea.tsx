import { forwardRef } from 'react'
import { cn } from '@/utils/helpers'

interface ScrollAreaProps extends React.HTMLAttributes<HTMLDivElement> {
  horizontal?: boolean
}

export const ScrollArea = forwardRef<HTMLDivElement, ScrollAreaProps>(
  ({ className, horizontal, children, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'scrollbar-thin',
        horizontal ? 'flex overflow-x-auto' : 'overflow-y-auto',
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
)

ScrollArea.displayName = 'ScrollArea'