# Install Azure CLI if not already installed
# https://docs.microsoft.com/en-us/cli/azure/install-azure-cli

# Check if user is logged in
az account show
if ($LASTEXITCODE -ne 0) {
    return
}

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$rootDirectory = Split-Path $scriptDirectory -Parent

# Define the path to your .env file
$envFilePath = "$rootDirectory\src\.env"

# Load the environment variables
Import-Csv $envFilePath -Delimiter '=' -Header Key,Value | ForEach-Object {
    [System.Environment]::SetEnvironmentVariable($_.Key, $_.Value)
}

# Upload patient data to FHIR service
if ($env:CLINICAL_NOTES_SOURCE -eq "fhir") {
    Write-Output "CLINICAL_NOTES_SOURCE is set to ""fhir"". Uploading patient data to FHIR service..."

    # Ensure Python is installed
    $pythonOutput = &{python -V}
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Python is not installed or not found in PATH. Please install Python and try again."
        exit 1
    }
    
    # Check if python version is 3.12 or higher
    $pythonVersion = [version]$pythonOutput.Split(" ")[1]
    Write-Output "  Python version: $pythonVersion"
    if ($pythonVersion -lt [version]"3.12") {
        Write-Error "Python version 3.12 or higher is required. Please update Python and try again."
        exit 1
    }

    # Run the Python script to convert patient data to FHIR format
    Write-Output "  Generating FHIR resources from patient data..."
    python "$rootDirectory\scripts\generate_fhir_resources.py"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to generate FHIR resources. Please check the script for errors."
        exit 1
    }

    # Run the Python script to upload patient data to FHIR service
    Write-Output "  Uploading FHIR resources into the FHIR service..."
    $authToken = (ConvertFrom-SecureString -AsPlainText (Get-AzAccessToken -AsSecureString -ResourceUrl $env:FHIR_SERVICE_ENDPOINT -Tenant $tenantId).Token)
    python "$rootDirectory\scripts\ingest_fhir_resources.py" `
        --fhir-url $env:FHIR_SERVICE_ENDPOINT `
        --auth-token $authToken `
        --azure-env-name $env:AZURE_ENV_NAME
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to ingest FHIR resources. Please check the script for errors."
        exit 1
    }

    exit 0
}

# Define variables
$storageAccountName = $env:APP_STORAGE_ACCOUNT_NAME
$containerName = "patient-data"
$localFolderPath = "$rootDirectory\infra\patient_data"

# Upload files
Get-ChildItem -Path $localFolderPath | ForEach-Object {
    $path = $_.FullName
    $patientFolder = $path.Substring($localFolderPath.Length + 1).Replace("\", "/")

    if (Test-Path -Path $path -PathType Container) {
        Write-Output "Deleting patient data for $patientFolder"
        az storage blob delete-batch --account-name $storageAccountName --source $containerName --pattern "$patientFolder/*" --auth-mode login

        Write-Output "Uploading patient data from $path"
        az storage blob upload-batch --account-name $storageAccountName --destination "$containerName/$patientFolder" --source $path --auth-mode login --overwrite true
    }
}
