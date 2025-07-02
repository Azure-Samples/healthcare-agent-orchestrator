#!/bin/bash

# Install Azure CLI if not already installed
# https://docs.microsoft.com/en-us/cli/azure/install-azure-cli


if [ "$AZURE_PRINCIPAL_TYPE" == "ServicePrincipal" ]; then
    echo "Running as ServicePrincipal. Skipping uploading data."
    exit 0
fi

# Check if user is logged in
if ! az account show &>/dev/null; then
    echo "You are not logged in to Azure. Please log in and try again."
    exit 1
fi

# Define the script and root directories
scriptDirectory=$(dirname "$(realpath "$0")")
rootDirectory=$(dirname "$scriptDirectory")

# Define the path to your .env file
envFilePath="$rootDirectory/src/.env"

# Load the environment variables
if [ -f "$envFilePath" ]; then
    source "$envFilePath"
else
    echo "Environment file not found at $envFilePath"
    exit 1
fi

if [ "$CLINICAL_NOTES_SOURCE" == "fhir" ]; then
    echo "CLINICAL_NOTES_SOURCE is set to \"fhir\". Uploading patient data to FHIR service..."

    # Check if Python is installed
    pythonVersion=$(python -V 2>&1 | grep -Po '(?<=Python )(.+)')
    if [[ -z "$pythonVersion" ]]; then
        echo "Python version 3.12 or higher is required. Please install Python and try again."
        exit 1
    fi

    pythonVersionArray=(${pythonVersion//./ })
    echo "  Python version: ${pythonVersionArray[0]}.${pythonVersionArray[1]}"
    if [[ ${pythonVersionArray[0]} -eq 3 && ${pythonVersionArray[1]} -lt 12 ]]; then
        echo "Python version 3.12 or higher is required. Please update your Python installation."
        exit 1
    fi

    # Run the Python script to convert patient data to FHIR format
    echo "  Generating FHIR resources from patient data..."
    python "$rootDirectory/scripts/generate_fhir_resources.py"
    if [ $? -ne 0 ]; then
        echo "Failed to generate FHIR resources. Please check the script for errors."
        exit 1
    fi

    # Run the Python script to upload patient data to FHIR service
    echo "  Uploading FHIR resources into the FHIR service..."
    authToken=$(az account get-access-token --resource "$FHIR_SERVICE_ENDPOINT" --tenant "$tenantId" --query accessToken -o tsv)
    if [ $? -ne 0 ]; then
        echo "Failed to obtain access token for FHIR service. If you're running from a device outside of your organization, such as Github Codespace, you'll need to obtain the access token from an approved device by your organization."
        exit 1
    fi

    python $rootDirectory/scripts/ingest_fhir_resources.py \
        --fhir-url "$FHIR_SERVICE_ENDPOINT" \
        --auth-token "$authToken" \
        --azure-env-name "$AZURE_ENV_NAME"
    if [ $? -ne 0 ]; then
        echo "Failed to ingest FHIR resources. Please check the script for errors."
        exit 1
    fi
    
    exit 0
fi

# Define variables
storageAccountName="$APP_STORAGE_ACCOUNT_NAME"
containerName="patient-data"
localFolderPath="$rootDirectory/infra/patient_data"

# Upload files
for path in "$localFolderPath"/*; do
    if [ -d "$path" ]; then
        patientFolder=$(basename "$path")

        echo "Deleting patient data for $patientFolder"
        az storage blob delete-batch --account-name "$storageAccountName" --source "$containerName" --pattern "$patientFolder/*" --auth-mode login

        echo "Uploading patient data from $path"
        az storage blob upload-batch --account-name "$storageAccountName" --destination "$containerName/$patientFolder" --source "$path" --auth-mode login --overwrite true
    fi
done