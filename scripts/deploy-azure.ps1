param(
    [Parameter(Mandatory)][string]$SubscriptionId,
    [Parameter(Mandatory)][string]$ResourceGroup,
    [Parameter(Mandatory)][string]$Location,
    [Parameter(Mandatory)][string]$AppName,
    [string]$PlanName = "$AppName-plan",
    [string]$Sku = 'B1'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
function Invoke-Azure {
    & az @args
    if ($LASTEXITCODE -ne 0) { throw 'Azure command failed' }
}
Push-Location $projectRoot
try {
    Push-Location frontend
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    } finally { Pop-Location }
    & "$projectRoot/.venv/Scripts/python.exe" scripts/package.py
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }
    Invoke-Azure account set --subscription $SubscriptionId
    Invoke-Azure group create --name $ResourceGroup --location $Location --output none
    Invoke-Azure appservice plan create --name $PlanName --resource-group $ResourceGroup --location $Location --is-linux --sku $Sku --output none
    Invoke-Azure webapp create --name $AppName --resource-group $ResourceGroup --plan $PlanName --runtime 'PYTHON:3.14' --output none
    Invoke-Azure webapp update --name $AppName --resource-group $ResourceGroup --https-only true --output none
    Invoke-Azure webapp config set --name $AppName --resource-group $ResourceGroup --startup-file 'python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 2' --always-on true --min-tls-version '1.2' --output none
    Invoke-Azure webapp config appsettings set --name $AppName --resource-group $ResourceGroup --settings SCM_DO_BUILD_DURING_DEPLOYMENT=true --output none
    Invoke-Azure webapp deploy --name $AppName --resource-group $ResourceGroup --src-path "$projectRoot/artifacts/app.zip" --type zip --output none
    $hostName = Invoke-Azure webapp show --name $AppName --resource-group $ResourceGroup --query defaultHostName --output tsv
    & "$projectRoot/.venv/Scripts/python.exe" scripts/verify_deployment.py "https://$hostName"
    if ($LASTEXITCODE -ne 0) { throw 'Deployed app verification failed' }
    Write-Host "Verified deployment: https://$hostName"
} finally { Pop-Location }
