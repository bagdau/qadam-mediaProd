# Generates .\secrets\* for compose.prod.yaml. Existing files are never overwritten.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force secrets | Out-Null

function New-RandomText([int]$Length = 40) {
  $bytes = New-Object byte[] 64
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
  ([Convert]::ToBase64String($bytes) -replace '[/+=]', '').Substring(0, $Length)
}
function New-FernetKey {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
  [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_')
}
function Save-Secret($Name, [string]$Value) {
  $path = Join-Path secrets $Name
  if ((Test-Path $path) -and (Get-Item $path).Length -gt 0) { Write-Host "keep   secrets/$Name"; return }
  [IO.File]::WriteAllText((Resolve-Path secrets).Path + "\$Name", $Value)
  Write-Host "create secrets/$Name"
}
Save-Secret postgres_password (New-RandomText 40)
Save-Secret redis_password (New-RandomText 40)
Save-Secret secret_key (New-RandomText 64)
Save-Secret encryption_keys (New-FernetKey)
if (-not (Test-Path secrets/tiktok_client_secret)) { Save-Secret tiktok_client_secret ''; Write-Host 'secrets/tiktok_client_secret is EMPTY - paste your TikTok client secret into it' }
Save-Secret bootstrap_admin_password (New-RandomText 24)
Write-Host "`nBack up secrets/encryption_keys: without it stored TikTok tokens cannot be decrypted."
