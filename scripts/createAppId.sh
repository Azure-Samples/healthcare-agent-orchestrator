#!/bin/bash

# Parse command line arguments
AZURE_TENANT_ID=$1
SERVICE_MANAGEMENT_REFERENCE=$2

CLIENT_ID=""
AZURE_ENV_NAME=""

# Get environment variables from azd
env_values=$(azd env get-values)

# Parse the environment values
while IFS= read -r line; do
    key=$(echo "$line" | cut -d '=' -f 1)
    value=$(echo "$line" | cut -d '=' -f 2- | sed 's/^"//' | sed 's/"$//')
    
    if [ "$key" = "CLIENT_ID" ]; then
        CLIENT_ID=$value
    fi
    
    if [ "$key" = "AZURE_ENV_NAME" ]; then
        AZURE_ENV_NAME=$value
    fi
done <<< "$env_values"

# If App Registration was not created, create it
if [ -z "$CLIENT_ID" ]; then
    echo "Creating app registration..."
    APP=$(az ad app create --display-name "$AZURE_ENV_NAME" --enable-id-token-issuance --required-resource-accesses "@scripts/permissions.json" --service-management-reference "$SERVICE_MANAGEMENT_REFERENCE")
    CLIENT_ID=$(echo $APP | jq -r '.appId')
    azd env set CLIENT_ID $CLIENT_ID
else
    echo "App registration already exists. Skipping..."
fi
