param(
  [switch]$Down,
  [switch]$Logs,
  [switch]$NoBuild
)

$mode = "prod"
if ($Down) {
  & "$PSScriptRoot\compose.ps1" -Mode down
  exit $LASTEXITCODE
}
if ($Logs) {
  & "$PSScriptRoot\compose.ps1" -Mode logs
  exit $LASTEXITCODE
}
& "$PSScriptRoot\compose.ps1" -Mode $mode -NoBuild:$NoBuild
