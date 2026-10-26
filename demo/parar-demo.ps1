# Para a demonstração. Use: .\parar-demo.ps1 -Apagar   para remover também os dados e a imagem.
param([switch]$Apagar)
Set-Location $PSScriptRoot
Get-Content .\demo.env | Where-Object { $_ -match '^\s*([A-Z_]+)=' } | ForEach-Object {
  $k, $v = ($_ -replace '"', '').Split('=', 2); [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), "Process")
}
if ($Apagar) {
  docker compose -p capacity-agent-demo -f compose.yaml down -v
  docker image rm "capacity-agent-demo:$($env:DEMO_VERSION)" *> $null
  Remove-Item .\senha-demo.txt -ErrorAction SilentlyContinue
  Write-Host "Demonstração removida (dados e imagem)."
} else {
  docker compose -p capacity-agent-demo -f compose.yaml stop
  Write-Host "Demonstração parada. Para voltar: .\iniciar-demo.ps1"
}
