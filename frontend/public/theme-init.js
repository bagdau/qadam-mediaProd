// Applies the stored theme before first paint (kept as a file so the CSP can stay script-src 'self').
try {
  var t = localStorage.getItem('qm-theme') || 'system'
  var dark = t === 'dark' || (t === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
  if (dark) document.documentElement.classList.add('dark')
} catch (e) {}
