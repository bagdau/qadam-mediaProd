$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  python -m venv (Join-Path $Root ".venv")
  & $Python -m pip install -r (Join-Path $Root "requirements.txt")
}
if (-not (Test-Path (Join-Path $Root ".env"))) {
  Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env")
}
Set-Location $Root
& $Python -m uvicorn app.main:app --host 0.0.0.0 --port 8100

