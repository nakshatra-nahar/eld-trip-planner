import { LoaderCircle } from 'lucide-react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/cn'

type Variant = 'primary' | 'accent' | 'secondary' | 'ghost'
type Size = 'sm' | 'md' | 'lg' | 'icon'

const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-ink-900 text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.08),0_1px_2px_rgb(8_14_28/0.3)] hover:bg-ink-800 active:bg-ink-950',
  accent:
    'bg-hw-500 text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.2),0_1px_2px_rgb(169_64_12/0.35)] hover:bg-hw-600 active:bg-hw-700',
  secondary: 'bg-white text-ink-800 ring-1 ring-inset ring-ink-200 hover:bg-ink-50 hover:ring-ink-300',
  ghost: 'text-ink-600 hover:bg-ink-150 hover:text-ink-900',
}

const SIZES: Record<Size, string> = {
  sm: 'h-9 px-3 text-[13px] gap-1.5 rounded-lg',
  md: 'h-11 px-4 text-sm gap-2 rounded-[10px]',
  lg: 'h-12 px-5 text-[15px] gap-2 rounded-xl',
  icon: 'size-11 rounded-[10px] justify-center',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: ReactNode
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  icon,
  className,
  children,
  disabled,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        'inline-flex shrink-0 items-center justify-center font-medium whitespace-nowrap transition-[background-color,box-shadow,color,transform] duration-150 select-none active:translate-y-px disabled:pointer-events-none disabled:opacity-55',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  )
}
