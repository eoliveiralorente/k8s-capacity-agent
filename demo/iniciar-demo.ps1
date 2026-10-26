# Capacity Agent — inicia a demonstração local (Windows, PowerShell). Requer Docker Desktop.
# Se o Windows bloquear: clique com o botão direito → "Executar com o PowerShell",
# ou rode: powershell -ExecutionPolicy Bypass -File .\iniciar-demo.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Get-Content .\demo.env | Where-Object { $_ -match '^\s*([A-Z_]+)="?([^"]*)"?\s*$' } | ForEach-Object {
  $k, $v = ($_ -replace '"', '').Split('=', 2); [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), "Process")
}
$ver = $env:DEMO_VERSION; $port = $env:DEMO_PORT

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Host "Instale o Docker Desktop e rode de novo."; exit 1 }
docker info *> $null; if ($LASTEXITCODE -ne 0) { Write-Host "Abra o Docker Desktop e rode de novo."; exit 1 }

docker image inspect "capacity-agent-demo:$ver" *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Carregando a imagem (só na primeira vez, cerca de 1 minuto)..."
  docker load -i capacity-agent-demo-image.tar.gz
}
docker compose -p capacity-agent-demo -f compose.yaml up -d

Write-Host "Aguardando o painel subir..."
for ($i = 0; $i -lt 60; $i++) {
  docker compose -p capacity-agent-demo exec -T capacity-agent-demo python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)" *> $null
  if ($LASTEXITCODE -eq 0) { break }
  Start-Sleep -Seconds 2
}

if (-not (Test-Path .\senha-demo.txt)) {
  $chars = [char[]]'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
  -join (1..14 | ForEach-Object { $chars | Get-Random }) | Set-Content -NoNewline .\senha-demo.txt
}
$pass = (Get-Content .\senha-demo.txt -Raw).Trim()
docker compose -p capacity-agent-demo exec -T capacity-agent-demo python agent.py demo --email demo@capacity-agent.local --password $pass | Out-Null

Write-Host ""
Write-Host "Demonstração pronta:"
Write-Host "  Endereço: http://localhost:$port"
Write-Host "  Login:    demo@capacity-agent.local"
Write-Host "  Senha:    $pass   (também em senha-demo.txt)"
Start-Process "http://localhost:$port"
