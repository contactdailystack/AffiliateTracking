param(
  [ValidateSet("dev", "test", "prod", "down", "logs", "config")]
  [string]$Mode = "dev",
  [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Invoke-Compose {
  param([string[]]$cmdArgs)
  & docker compose @cmdArgs
  if ($LASTEXITCODE -ne 0) {
    throw "docker compose failed: $($cmdArgs -join ' ')"
  }
}

switch ($Mode) {
  "dev" {
    $composeParams = @("up")
    if (-not $NoBuild) { $composeParams += "--build" }
    Invoke-Compose -cmdArgs $composeParams
  }
  "test" {
    $composeParams = @("-f", "docker-compose.yml", "-f", "docker-compose.test.yml", "up", "--abort-on-container-exit", "--exit-code-from", "tests")
    if (-not $NoBuild) { $composeParams = $composeParams[0..4] + @("--build") + $composeParams[5..($composeParams.Length - 1)] }
    Invoke-Compose -cmdArgs $composeParams
  }
  "prod" {
    $composeArgs = @("-f", "docker-compose.yml", "-f", "docker-compose.prod.yml")
    Invoke-Compose -cmdArgs ($composeArgs + @("config"))
    $upArgs = $composeArgs + @("up", "-d")
    if (-not $NoBuild) { $upArgs += "--build" }
    Invoke-Compose -cmdArgs $upArgs
  }
  "down" {
    Invoke-Compose -cmdArgs @("down", "-v", "--remove-orphans")
  }
  "logs" {
    Invoke-Compose -cmdArgs @("logs", "-f", "--tail", "100")
  }
  "config" {
    Invoke-Compose -cmdArgs @("config")
  }
}
