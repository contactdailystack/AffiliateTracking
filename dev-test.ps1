param(
  [ValidateSet("dev", "test", "prod", "down", "logs", "config")]
  [string]$Mode = "dev",
  [switch]$NoBuild
)

& "$PSScriptRoot\compose.ps1" -Mode $Mode -NoBuild:$NoBuild
