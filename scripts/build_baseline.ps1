param(
    [Parameter(Mandatory = $true)]
    [string]$ComsolRoot
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceFile = Join-Path $projectRoot "src\comsol\BaselinePipe2D.java"
$classFile = Join-Path $projectRoot "src\comsol\BaselinePipe2D.class"
$outputFile = Join-Path $projectRoot "models\baseline_pipe_2d_laminar.mph"
$runDir = Join-Path $projectRoot ("outputs\baseline\" + (Get-Date -Format "yyyyMMdd-HHmmss"))
$logFile = Join-Path $runDir "batch.log"
$reportFile = Join-Path $projectRoot "outputs\baseline\verification.json"
$compiler = Join-Path $ComsolRoot "bin\win64\comsolcompile.exe"
$batch = Join-Path $ComsolRoot "bin\win64\comsolbatch.exe"

if (-not (Test-Path -LiteralPath $compiler)) {
    throw "COMSOL compiler not found: $compiler"
}

if (-not (Test-Path -LiteralPath $batch)) {
    throw "COMSOL batch executable not found: $batch"
}

if (Test-Path -LiteralPath $outputFile) {
    throw "Baseline exists: $outputFile. Move it before rebuilding."
}
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
Push-Location $projectRoot
try {
    $compileStarted = Get-Date
    & $compiler $sourceFile
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $classFile) -or
        (Get-Item -LiteralPath $classFile).LastWriteTime -lt $compileStarted) {
        throw "COMSOL Java compilation failed with exit code $LASTEXITCODE"
    }

    $batchOutput = & $batch -inputfile $classFile -outputfile (Join-Path $runDir "batch.mph") -batchlog $logFile -batchlogout -np 2 2>&1
    $batchExit = $LASTEXITCODE
    # COMSOL may return zero even if Java execution fails. Require the success marker.
    $logText = ($batchOutput | ForEach-Object { "$_" }) -join "`n"
    if ($batchExit -ne 0 -or -not (Test-Path -LiteralPath $outputFile) -or
        $logText -notmatch "FLOWPILOT_BASELINE_VERIFIED") {
        $batchOutput | Select-Object -Last 20 | Write-Host
        throw "COMSOL batch generation failed with exit code $batchExit. See $logFile"
    }
    $jsonLine = @($batchOutput | ForEach-Object { "$_" } | Where-Object { $_.StartsWith("FLOWPILOT_VERIFICATION_JSON ") })
    if (@($jsonLine).Count -ne 1) { throw "Missing or ambiguous verification report: $logFile" }
    $report = $jsonLine[0].Substring("FLOWPILOT_VERIFICATION_JSON ".Length) | ConvertFrom-Json
    $report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $reportFile -Encoding utf8
}
finally {
    Pop-Location
}

Write-Host "Generated: $outputFile"
Write-Host "Log:       $logFile"
Write-Host "Report:    $reportFile"
