param([Parameter(Mandatory = $true)][string]$ComsolRoot, [switch]$InspectOnly, [switch]$PrepareOnly)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceDir = Join-Path $projectRoot "src\comsol"
$caseDir = Join-Path $projectRoot "models\cases"
$runDir = Join-Path $projectRoot ("outputs\cases\" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$compiler = Join-Path $ComsolRoot "bin\win64\comsolcompile.exe"
$batch = Join-Path $ComsolRoot "bin\win64\comsolbatch.exe"
foreach ($required in @($compiler, $batch, (Join-Path $projectRoot "models\baseline_pipe_2d_laminar.mph"))) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required file not found: $required" }
}
foreach ($name in @("missing_inlet", "missing_outlet", "selection_overlap", "reversed_inlet", "high_reynolds")) {
    $exists = Test-Path -LiteralPath (Join-Path $caseDir "$name.mph")
    if ($InspectOnly -and -not $exists) { throw "Missing saved case: $name" }
    if (-not $InspectOnly -and $exists) { throw "Archive existing case before regenerating: $name" }
}
New-Item -ItemType Directory -Path $runDir, $caseDir -Force | Out-Null
Push-Location $projectRoot
try {
    # COMSOL's batch input-class loader did not resolve a sibling helper class.
    # Generate a self-contained driver from the same inventory source; no copied logic.
    $driver = Join-Path $runDir "BoundaryCases.java"
    $source = Get-Content -LiteralPath (Join-Path $sourceDir "ModelInventory.java") -Raw
    $source = $source.Replace("public class ModelInventory", "public class BoundaryCases")
    $source = $source.Replace("public static void main(String[] args)", "public static void inspectBaseline(String[] args)")
    $entry = if ($InspectOnly) { "inspectCases" } else { "buildCases" }
    $source = $source.Replace("public static void $entry(String[] args)", "public static void main(String[] args)")
    Set-Content -LiteralPath $driver -Value $source -Encoding utf8NoBOM
    if ($PrepareOnly) { Write-Host "Driver prepared: $driver"; return }
    $started = Get-Date
    & $compiler $driver
    $class = Join-Path $runDir "BoundaryCases.class"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $class) -or (Get-Item -LiteralPath $class).LastWriteTime -lt $started) {
        throw "Case driver compilation failed"
    }
    $output = & $batch -inputfile $class -nosave -batchlog (Join-Path $runDir "batch.log") -batchlogout -np 2 2>&1
    $exitCode = $LASTEXITCODE
    $lines = @($output | ForEach-Object { "$_" })
    if ($exitCode -ne 0 -or ($lines -join "`n") -notmatch "FLOWPILOT_CASES_VERIFIED 5") {
        $lines | Select-Object -Last 20 | Write-Host
        throw "Case generation failed; see $runDir"
    }
    $reports = @($lines | Where-Object { $_.StartsWith("FLOWPILOT_CASE_JSON ") })
    if ($reports.Count -ne 5) { throw "Expected exactly five reports" }
    foreach ($line in $reports) {
        $report = $line.Substring("FLOWPILOT_CASE_JSON ".Length) | ConvertFrom-Json
        $report.inventory | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath (Join-Path $runDir ($report.case_id + ".json")) -Encoding utf8
    }
    Write-Host "Verified five saved cases, five loads each. Inventories: $runDir"
} finally { Pop-Location }
