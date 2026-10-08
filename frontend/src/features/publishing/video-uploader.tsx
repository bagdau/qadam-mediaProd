import { FileVideo, Trash2, UploadCloud } from 'lucide-react'
import { useId, useRef, useState, type DragEvent } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { mediaApi } from '@/services/api'
import { errorMessage } from '@/services/http'
import type { MediaAsset } from '@/types/api'
import { cn } from '@/utils/cn'
import { formatBytes, formatDuration } from '@/utils/format'
import { readVideoDuration } from '@/utils/video'
import { checkFile } from './rules'

interface Props {
  maxMb: number
  media: MediaAsset | null
  onChange: (media: MediaAsset | null) => void
  disabled?: boolean
  error?: string
}

export function VideoUploader({ maxMb, media, onChange, disabled, error }: Props) {
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const [progress, setProgress] = useState<number | null>(null)
  const [fileName, setFileName] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)

  async function handleFile(file: File | undefined) {
    if (!file) return
    setLocalError(null)
    const check = checkFile(file, maxMb)
    if (!check.ok) {
      setLocalError(check.error ?? 'Файл не подходит')
      return
    }
    setFileName(file.name)
    setProgress(0)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const duration = await readVideoDuration(file)
      const uploaded = await mediaApi.upload(file, duration, setProgress, controller.signal)
      onChange(uploaded)
      toast.success('Видео загружено')
    } catch (e) {
      if (controller.signal.aborted) return
      setLocalError(errorMessage(e, 'Не удалось загрузить видео'))
    } finally {
      setProgress(null)
      abortRef.current = null
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  async function remove() {
    const current = media
    onChange(null)
    if (current) {
      try {
        await mediaApi.remove(current.id)
      } catch {
        /* the cleanup job removes unused files anyway */
      }
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    setDragging(false)
    if (!disabled) void handleFile(e.dataTransfer.files[0])
  }

  const uploading = progress !== null
  const shownError = localError ?? error

  return (
    <div className="space-y-2">
      {media ? (
        <div className="flex items-center gap-3 rounded-lg border bg-card p-3">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-md bg-accent text-accent-foreground">
            <FileVideo className="size-5" aria-hidden />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{media.original_filename}</p>
            <p className="text-xs text-muted-foreground">
              {formatBytes(media.size_bytes)} · {formatDuration(media.duration_seconds)}
            </p>
          </div>
          <Button type="button" variant="ghost" size="icon" onClick={remove} disabled={disabled} aria-label={`Убрать видео ${media.original_filename}`}>
            <Trash2 aria-hidden />
          </Button>
        </div>
      ) : uploading ? (
        <div className="space-y-2 rounded-lg border bg-card p-4" role="status" aria-live="polite">
          <div className="flex items-center justify-between gap-2 text-sm">
            <span className="truncate font-medium">{fileName}</span>
            <span className="tabular-nums text-muted-foreground">{progress}%</span>
          </div>
          <Progress value={progress} aria-label="Загрузка видео" />
          <Button type="button" variant="ghost" size="sm" onClick={() => abortRef.current?.abort()}>
            Отменить загрузку
          </Button>
        </div>
      ) : (
        <label
          htmlFor={inputId}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed bg-card px-4 py-10 text-center transition-colors hover:border-primary/60 hover:bg-accent/40',
            dragging && 'border-primary bg-accent/60',
            disabled && 'pointer-events-none opacity-50',
            shownError && 'border-destructive/60',
          )}
        >
          <UploadCloud className="size-8 text-muted-foreground" aria-hidden />
          <span className="text-sm font-medium">Перетащите видео сюда или нажмите, чтобы выбрать</span>
          <span className="text-xs text-muted-foreground">MP4, MOV или WebM · до {maxMb} МБ</span>
        </label>
      )}
      <input
        id={inputId}
        ref={inputRef}
        type="file"
        accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm"
        className="sr-only"
        disabled={disabled || uploading || !!media}
        onChange={(e) => void handleFile(e.target.files?.[0])}
        aria-label="Файл видео"
      />
      {shownError && (
        <p role="alert" className="text-sm text-destructive">
          {shownError}
        </p>
      )}
    </div>
  )
}
