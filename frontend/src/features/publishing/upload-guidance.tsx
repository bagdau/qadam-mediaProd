export function UploadGuidance({ maximumMegabytes }: { maximumMegabytes: number }) {
  return (
    <aside className="text-sm text-muted-foreground" aria-label="Требования к видео">
      MP4, MOV или WebM. Максимальный размер: {maximumMegabytes} МБ. Не закрывайте вкладку до окончания загрузки.
    </aside>
  )
}
