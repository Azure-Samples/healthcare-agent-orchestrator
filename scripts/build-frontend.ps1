# Build script for the React frontend

# Exit on error
$ErrorActionPreference = "Stop"

$scriptDir = $PSScriptRoot
$projectRoot = Split-Path -Parent $scriptDir
$democlientDir = Join-Path -Path $projectRoot -ChildPath "democlient"
$srcDir = Join-Path -Path $democlientDir -ChildPath "src"
$buildDir = Join-Path -Path $democlientDir -ChildPath "build"
$staticDir = Join-Path -Path $projectRoot -ChildPath "src\static"

# Get environment values
Write-Host "Getting environment variables from azd..."
$azdEnvOutput = azd env get-values
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: azd env get-values failed with exit code $LASTEXITCODE"
    exit 1
}
$envValues = @{}
$azdEnvOutput | ForEach-Object {
    $parts = $_ -split '='
    if ($parts.Count -eq 2) {
        $key = $parts[0]
        $value = $parts[1] -replace '^"', '' -replace '"$', ''  # Remove quotes if present
        $envValues[$key] = $value
    }
}

# Check if frontend build is disabled
if ($envValues["DISABLE_FRONT_END"] -eq "true") {
    Write-Host "Frontend build is disabled (DISABLE_FRONT_END=true). Skipping frontend build."
    exit 0
}

# Check if Node.js is installed
try {
    $nodeVersion = node --version
    Write-Host "Node.js version: $nodeVersion"
} catch {
    Write-Host "Node.js is required for frontend build but not installed."
    exit 1
}

# Check if npm is installed
try {
    $npmVersion = npm --version
    Write-Host "npm version: $npmVersion"
} catch {
    Write-Host "npm is required for frontend build but not installed."
    exit 1
}

# Navigate to the React project directory
Set-Location $democlientDir

Write-Host "Installing frontend dependencies..."
npm install
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: npm install failed with exit code $LASTEXITCODE"
    exit 1
}

# Create .env.production file with Vite environment variables
Write-Host "Creating .env.production with environment variables..."
$reactAppApiBaseUrl = $envValues["REACT_APP_API_BASE_URL"]
if (-not $reactAppApiBaseUrl) {
    $reactAppApiBaseUrl = ""
}

$envContent = "VITE_API_BASE_URL=$reactAppApiBaseUrl"
$envContent | Out-File -FilePath ".env.production" -Encoding UTF8

Write-Host "Building React frontend..."
npm run build
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: npm run build failed with exit code $LASTEXITCODE"
    exit 1
}

# Check if build was successful
if (-not (Test-Path $buildDir)) {
    Write-Host "Error: Build directory does not exist. Frontend build may have failed."
    exit 1
}

Write-Host "Copying build files to src/static/static directory for deployment..."

# Create the static directory structure that the Python app expects
$staticStaticDir = Join-Path -Path $staticDir -ChildPath "static"
if (-not (Test-Path $staticDir)) {
    New-Item -ItemType Directory -Path $staticDir -Force
}
if (-not (Test-Path $staticStaticDir)) {
    New-Item -ItemType Directory -Path $staticStaticDir -Force
}

# Remove existing files in the target directory
if (Test-Path $staticStaticDir) {
    Remove-Item -Path "$staticStaticDir\*" -Recurse -Force
}

# Copy all build files to the static/static directory (note the double static)
Copy-Item -Path "$buildDir\*" -Destination $staticStaticDir -Recurse -Force

Write-Host "Frontend build completed successfully!"
Write-Host "Files copied to: $staticStaticDir"
Write-Host "Build contents:"
Get-ChildItem $staticStaticDir 