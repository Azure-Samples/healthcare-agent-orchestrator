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
if ($envValues.ContainsKey("DISABLE_FRONT_END") -and $envValues["DISABLE_FRONT_END"] -eq "true") {
    Write-Host "Frontend build is disabled (DISABLE_FRONT_END=true). Skipping frontend build."
    exit 0
}

# Check if Node.js is installed
try {
    $nodeVersion = node -v
    Write-Host "Node.js version: $nodeVersion"
} catch {
    Write-Host "Node.js is required for frontend build but not installed."
    $skipFrontend = Read-Host "Do you want to skip the frontend build? (y/n)"
    if ($skipFrontend -eq "y" -or $skipFrontend -eq "Y") {
        Write-Host "Skipping frontend build. Note that the application may not function properly without a built frontend."
        exit 0
    } else {
        Write-Host "Please install Node.js and try again."
        exit 1
    }
}

# Navigate to the democlient directory
Set-Location -Path $democlientDir

# Check if env file exists and get its content
$envFile = ".env.production"
$envFilePath = Join-Path -Path $democlientDir -ChildPath $envFile
$existingEnvContent = ""
$envFileChanged = $true

if (Test-Path -Path $envFilePath) {
    $existingEnvContent = Get-Content -Path $envFilePath
}

# Create environment file for React if it doesn't exist or content is different
$envContent = @"
REACT_APP_API_BASE_URL=/api
"@

if ($existingEnvContent -eq $envContent) {
    Write-Host "Environment file exists and content is unchanged."
    $envFileChanged = $false
} else {
    Write-Host "Creating or updating $envFile file..."
    $envContent | Out-File -FilePath $envFile -Encoding utf8
}

# Function to check if build is needed
function NeedRebuild {
    param (
        [string]$Force,
        [bool]$EnvFileChanged
    )

    # Always build if the --force flag is passed
    if ($Force -eq "--force") {
        Write-Host "Force rebuild requested."
        return $true
    }

    # Always build if build directory doesn't exist
    if (-not (Test-Path -Path $buildDir)) {
        Write-Host "Build directory doesn't exist. Build needed."
        return $true
    }

    # Use index.html as reference file instead of directory timestamp
    $buildIndexFile = Join-Path -Path $buildDir -ChildPath "index.html"
    if (-not (Test-Path -Path $buildIndexFile)) {
        Write-Host "Build output file (index.html) doesn't exist. Build needed."
        return $true
    }
    
    # Get the build output file's last write time
    $buildLastWriteTime = (Get-Item -Path $buildIndexFile).LastWriteTime

    # Check if any source files are newer than the build output file
    $newerFiles = Get-ChildItem -Path $srcDir -Recurse -File | Where-Object { $_.LastWriteTime -gt $buildLastWriteTime }
    if ($null -ne $newerFiles -and $newerFiles.Count -gt 0) {
        Write-Host "Source files have changed. Build needed."
        return $true
    }

    # Check if package-lock.json is newer than build output file
    $packageLockJson = Join-Path -Path $democlientDir -ChildPath "package-lock.json"
    if (Test-Path -Path $packageLockJson) {
        $packageLockJsonLastWriteTime = (Get-Item -Path $packageLockJson).LastWriteTime
        if ($packageLockJsonLastWriteTime -gt $buildLastWriteTime) {
            Write-Host "package-lock.json has changed. Build needed."
            return $true
        }
    }

    # Check if env file has changed
    if ($EnvFileChanged) {
        Write-Host "Environment file has changed. Build needed."
        return $true
    }

    Write-Host "No changes detected. Skipping build."
    return $false
}

# Install dependencies if needed
if (-not (Test-Path -Path "node_modules") -or $args[0] -eq "--force") {
    Write-Host "Installing dependencies from package-lock.json..."
    npm ci
}

# Check if we need to rebuild
if (NeedRebuild -Force $args[0] -EnvFileChanged $envFileChanged) {
    # Build the React app
    Write-Host "Building React app..."
    npm run build
    Write-Host "Frontend build completed successfully!"
} else {
    Write-Host "Using existing build."
}

# Copy the build directory to src/static for deployment
Write-Host "Copying build files to src/static directory for deployment..."
if (-not (Test-Path -Path $staticDir)) {
    New-Item -Path $staticDir -ItemType Directory -Force
} else {
    Get-ChildItem -Path $staticDir -Recurse | Remove-Item -Force -Recurse
}
Copy-Item -Path "$buildDir\*" -Destination $staticDir -Recurse -Force
Write-Host "Files copied successfully!" 