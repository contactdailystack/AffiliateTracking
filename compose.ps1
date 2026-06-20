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
  param([string[]]$Args)
  & docker compose @Args
  if ($LASTEXITCODE -ne 0) {
    throw "docker compose failed: $($Args -join ' ')"
  }
}

switch ($Mode) {
  "dev" {
    $args = @("up")
    if (-not $NoBuild) { $args += "--build" }
    Invoke-Compose -Args $args
  }
  "test" {
    $args = @("-f", "docker-compose.yml", "-f", "docker-compose.test.yml", "up", "--abort-on-container-exit", "--exit-code-from", "tests")
    if (-not $NoBuild) { $args = $args[0..4] + @("--build") + $args[5..($args.Length - 1)] }
    Invoke-Compose -Args $args
  }
  "prod" {
    $composeArgs = @("-f", "docker-compose.yml", "-f", "docker-compose.prod.yml")
    Invoke-Compose -Args ($composeArgs + @("config"))
    $upArgs = $composeArgs + @("up", "-d")
    if (-not $NoBuild) { $upArgs += "--build" }
    Invoke-Compose -Args $upArgs
  }
  "down" {
    Invoke-Compose -Args @("down", "-v", "--remove-orphans")
  }
  "logs" {
    Invoke-Compose -Args @("logs", "-f", "--tail", "100")
  }
  "config" {
    Invoke-Compose -Args @("config")
  }
}
