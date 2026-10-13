import { cn } from '@/utils/helpers'

interface SeparatorProps extends React.HTMLAttributes<HTMLHRElement> {
  orientation?: 'horizontal' | 'vertical'
}

export const Separator = ({ className, orientation = 'horizontal', ...props }: SeparatorProps) => (
  <hr
    className={cn(
      'bg-eternix-800 border-0',
      orientation === 'horizontal' ? 'w-full h-px' : 'h-full w-px',
      className
    )}
    {...props}
  />
)