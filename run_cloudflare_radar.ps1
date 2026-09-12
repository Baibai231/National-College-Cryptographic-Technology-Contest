param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Remaining
)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}

& $Python (Join-Path $ProjectRoot "scripts\run_radar_measurement.py") @Remaining
exit $LASTEXITCODE
