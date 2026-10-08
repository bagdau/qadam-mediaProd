/** Reads the duration of a local video via browser metadata. Resolves null when it cannot be determined. */
export function readVideoDuration(file: File, timeoutMs = 8000): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const video = document.createElement('video')
    let done = false
    const finish = (value: number | null) => {
      if (done) return
      done = true
      clearTimeout(timer)
      URL.revokeObjectURL(url)
      video.removeAttribute('src')
      resolve(value)
    }
    const timer = setTimeout(() => finish(null), timeoutMs)
    video.preload = 'metadata'
    video.onloadedmetadata = () => finish(Number.isFinite(video.duration) ? video.duration : null)
    video.onerror = () => finish(null)
    video.src = url
  })
}
