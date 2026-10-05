import { ThinkingIllustration } from '@/components/ui/thinking-illustration'

export function RoutePendingFallback() {
  return (
    <div className="flex h-full min-h-24 min-w-0 items-center justify-center p-4 [&_.animate-bounce]:motion-reduce:animate-none" aria-busy="true">
      <ThinkingIllustration size="lg" />
    </div>
  )
}
