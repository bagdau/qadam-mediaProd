export function SkipLink({ target = 'main-content' }: { target?: string }) {
  return (
    <a href={`#${target}`} className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:bg-background focus:p-3">
      Перейти к основному содержимому
    </a>
  )
}
