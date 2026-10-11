param(
    [Parameter(Mandatory = $true)]
    [string]$ComsolRoot
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceFile = Join-Path $projectRoot "src\comsol\ModelInventory.java"
$classFile = Join-Path $projectRoot "src\comsol\ModelInventory.class"
$modelFile = Join-Path $projectRoot "models\baseline_pipe_2d_laminar.mph"
$runDir = Join-Path $projectRoot ("outputs\inventory\" + (Get-Date -Format "yyyyMMdd-HHmmss"))
$logFile = Join-Path $runDir "batch.log"
$compiler = Join-Path $ComsolRoot "bin\win64\comsolcompile.exe"
$batch = Join-Path $ComsolRoot "bin\win64\comsolbatch.exe"

foreach ($required in @($compiler, $batch, $modelFile)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required file not found: $required" }
}
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
Push-Location $projectRoot
try {
    $compileStarted = Get-Date
    & $compiler $sourceFile
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $classFile) -or
        (Get-Item -LiteralPath $classFile).LastWriteTime -lt $compileStarted) {
        throw "COMSOL inventory compilation failed"
    }
    $batchOutput = & $batch -inputfile $classFile -nosave -batchlog $logFile -batchlogout -np 2 2>&1
    $batchExit = $LASTEXITCODE
    $logText = ($batchOutput | ForEach-Object { "$_" }) -join "`n"
    if ($batchExit -ne 0 -or $logText -notmatch "FLOWPILOT_INVENTORY_VERIFIED 10") {
        $batchOutput | Select-Object -Last 20 | Write-Host
        throw "Inventory verification failed. See $logFile"
    }
    $jsonLine = @($batchOutput | ForEach-Object { "$_" } | Where-Object { $_.StartsWith("FLOWPILOT_INVENTORY_JSON ") })
    if (@($jsonLine).Count -ne 1) { throw "Missing or ambiguous inventory report" }
    $inventory = $jsonLine[0].Substring("FLOWPILOT_INVENTORY_JSON ".Length) | ConvertFrom-Json
    $output = Join-Path $runDir "inventory.json"
    $inventory | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $output -Encoding utf8
    Write-Host "Inventory: $output"
}
finally {
    Pop-Location
}
