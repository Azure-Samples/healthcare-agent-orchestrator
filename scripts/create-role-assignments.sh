#!/bin/bash
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

# Script to create role assignments for Healthcare Agent Orchestrator
# This script should be run by the Cloud Team (with Owner permissions) after the Dev Team has provisioned resources

# Prevent Git Bash (MSYS) from rewriting /subscriptions/... into a Windows path
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" || "$OSTYPE" == "cygwin" ]]; then
  export MSYS_NO_PATHCONV=1
  export MSYS2_ARG_CONV_EXCL="/subscriptions/*"
fi

# Track skipped role assignments for summary. Each entry formatted as:
# principalId|roleId|scope|description|reason
SKIPPED_PRINCIPALS=()

echo "=== Healthcare Agent Orchestrator - Role Assignment Script ==="
echo ""

# Resource Group
HAO_RESOURCE_GROUP=$(azd env get-value AZURE_RESOURCE_GROUP_NAME)
echo "Resource Group: $HAO_RESOURCE_GROUP"

# ============================================================================
# PRINCIPAL IDs
# ============================================================================

# Dev Team Principal IDs
# MANUAL INPUT REQUIRED: Add the Object IDs of all dev team members who need access
# To get a user's principal ID, run: az ad user show --id <user@domain.com> --query id -o tsv
# Example: DEV_TEAM_PRINCIPAL_IDS=("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" "ffffffff-0000-1111-2222-333333333333")
DEV_TEAM_PRINCIPAL_IDS=()

if [ ${#DEV_TEAM_PRINCIPAL_IDS[@]} -eq 0 ]; then
    echo "⚠ WARNING: No dev team principal IDs provided. Skipping dev team role assignments."
    echo "To add dev team members, get their Object IDs with: az ad user show --id <user@domain.com> --query id -o tsv"
    echo ""
fi

# Get all Managed Identity Principal IDs from the resource group
echo "Retrieving Managed Identity Principal IDs..."
IDENTITY_DATA=$(az identity list --resource-group "$HAO_RESOURCE_GROUP" --query "[].{name:name, principalId:principalId}" -o json)

# Extract all Agent names and Principal IDs (including Orchestrator)
AGENTS_PRINCIPAL_IDS=($(echo "$IDENTITY_DATA" | jq -r '.[].principalId'))
AGENT_NAMES=($(echo "$IDENTITY_DATA" | jq -r '.[].name'))
echo "Agent Principal IDs (${#AGENTS_PRINCIPAL_IDS[@]} total):"
for i in "${!AGENTS_PRINCIPAL_IDS[@]}"; do
    echo "  - ${AGENT_NAMES[$i]}: ${AGENTS_PRINCIPAL_IDS[$i]}"
done
echo ""

# Get AI Project's Managed Identity Principal ID
AI_PROJECT_NAME=$(az resource list \
    --resource-group "$HAO_RESOURCE_GROUP" \
    --resource-type "Microsoft.MachineLearningServices/workspaces" \
    --query "[0].name" -o tsv)
AI_PROJECT_PRINCIPAL_ID=$(az ml workspace show \
    --name "$AI_PROJECT_NAME" \
    --resource-group "$HAO_RESOURCE_GROUP" \
    --query identity.principal_id -o tsv)
echo "AI Project Principal ID: $AI_PROJECT_PRINCIPAL_ID"
echo ""

# ============================================================================
# ROLE DEFINITION IDs
# ============================================================================

# From aiservices.bicep
COG_SERVICES_OPENAI_CONTRIBUTOR_ROLE_ID="a001fd3d-188f-4b5d-821b-7da978bf7442"
COG_SERVICES_USER_ROLE_ID="a97b65f3-24c7-4388-baec-2e87135dc908"

# From aihub.bicep
AI_DEVELOPER_ROLE_ID="64702f94-c441-49e6-a78b-ef80e0188fee"

# From keyVault.bicep
SECRETS_OFFICER_ROLE_ID="b86a8fe4-44ce-4948-aee5-eccb2c155cd7"

# From storageAccount.bicep
STORAGE_BLOB_DATA_CONTRIBUTOR_ROLE_ID="ba92f5b4-2d11-453d-a403-e96b0029c9fe"

# From appinsights.bicep
MONITORING_METRICS_PUBLISHER_ROLE_ID="3913510d-42f4-4e42-8a64-420c390055eb"

# ============================================================================
# RESOURCE IDs
# ============================================================================

echo "Retrieving Azure Resource IDs..."

# AI Services
# AI_SERVICES_NAME=$(azd env get-value AZURE_OPENAI_NAME)
AI_SERVICES_RESOURCE_ID=$(az resource list \
    --resource-group "$HAO_RESOURCE_GROUP" \
    --resource-type "Microsoft.CognitiveServices/accounts" \
    --query "[0].id" -o tsv)
echo "AI Services: $AI_SERVICES_RESOURCE_ID"

# AI Hub
# AI_HUB_NAME=$(azd env get-value AZUREAI_HUB_NAME)
AI_HUB_RESOURCE_ID=$(az resource list \
    --resource-group "$HAO_RESOURCE_GROUP" \
    --resource-type "Microsoft.MachineLearningServices/workspaces" \
    --query "[0].id" -o tsv)
echo "AI Hub: $AI_HUB_RESOURCE_ID"

# AI Project
AI_PROJECT_RESOURCE_ID=$(az ml workspace show \
    --name "$AI_PROJECT_NAME" \
    --resource-group "$HAO_RESOURCE_GROUP" \
    --query id -o tsv)
echo "AI Project: $AI_PROJECT_RESOURCE_ID"

# Key Vault
# KEYVAULT_NAME=$(azd env get-value AZURE_KEYVAULT_NAME)
KEYVAULT_RESOURCE_ID=$(az resource list \
    --resource-group "$HAO_RESOURCE_GROUP" \
    --resource-type "Microsoft.KeyVault/vaults" \
    --query "[0].id" -o tsv)
echo "Key Vault: $KEYVAULT_RESOURCE_ID"

# Storage Account
# STORAGE_ACCOUNT_NAME=$(azd env get-value APP_STORAGE_ACCOUNT_NAME)
STORAGE_ACCOUNT_RESOURCE_ID=$(az resource list \
    --resource-group "$HAO_RESOURCE_GROUP" \
    --resource-type "Microsoft.Storage/storageAccounts" \
    --query "[0].id" -o tsv)
echo "Storage Account: $STORAGE_ACCOUNT_RESOURCE_ID"

# Application Insights (may not exist in all deployments)
APPINSIGHTS_RESOURCE_ID=$(az resource list \
    --resource-group "$HAO_RESOURCE_GROUP" \
    --resource-type "microsoft.insights/components" \
    --query "[0].id" -o tsv 2>/dev/null || echo "")

echo "Application Insights: $APPINSIGHTS_RESOURCE_ID"

echo ""
echo "=== Starting Role Assignment Creation ==="
echo ""

# ============================================================================
# HELPER FUNCTION
# ============================================================================

# Function to create role assignments for a list of principals
# Usage: assign_roles_to_principals PRINCIPAL_IDS_ARRAY ROLE_ID SCOPE_RESOURCE_ID DESCRIPTION PRINCIPAL_TYPE
assign_roles_to_principals() {
    local -n principals=$1
    local role_id=$2
    local scope=$3
    local description=$4
    local principal_type=$5
    
    if [ ${#principals[@]} -eq 0 ]; then
        echo "  Skipping $description: No principals provided"
        return
    fi
    
    echo "  Assigning role to $description (${#principals[@]} principals)..."
    for principal_id in "${principals[@]}"; do
        # Ensure the service principal exists in Azure AD (handles propagation delay)
        # echo "    Checking service principal for $principal_id..."
        # sp_exists=$(az ad sp show --id "$principal_id" --query id -o tsv 2>/dev/null || echo "")
        
        # if [ -z "$sp_exists" ]; then
        #     echo "    ⚠ Service principal not found in Azure AD, waiting for propagation..."
        #     # Wait up to 60 seconds for the service principal to appear
        #     for i in {1..6}; do
        #         sleep 10
        #         sp_exists=$(az ad sp show --id "$principal_id" --query id -o tsv 2>/dev/null || echo "")
        #         if [ -n "$sp_exists" ]; then
        #             echo "    ✓ Service principal now available"
        #             break
        #         fi
        #     done
            
        #     if [ -z "$sp_exists" ]; then
        #         echo "    ⚠ Service principal still not found after waiting. Attempting role assignment anyway..."
        #         echo "    → This may fail, but some managed identities work without explicit service principals"
        #     fi
        # fi
        

        echo "        Role ID: $role_id"
        echo "        Principal ID: $principal_id"
        echo "        Scope: $scope"
        # Check if assignment already exists
        # existing=$(az role assignment list \
        #     --assignee "$principal_id" \
        #     --role "$role_id" \
        #     --all \
        #     --query "[?scope=='$scope'].id | length(@)" -o tsv 2>/dev/null || echo 0)
        
        # if [[ "$existing" -gt 0 ]]; then
        #     echo "    ✓ Role $role_id already assigned to $principal_id"
        #     continue
        # fi

        # Not found; attempt create (capture output first, then inspect exit code)
        output=$(az role assignment create \
            --role "$role_id" \
            --assignee-object-id "$principal_id" \
            --assignee-principal-type "$principal_type" \
            --scope "$scope" 2>&1)
        
        # # Remove carriage returns that might be messing up output
        # output=$(echo "$output" | tr -d '\r')
        
        create_status=$?

        # DEBUG: Save raw output to file
        echo "=== Principal: $principal_id ===" >> ./tmp/role_assignment_debug.log
        echo "$output" >> ./tmp/role_assignment_debug.log
        echo "Exit status: $create_status" >> ./tmp/role_assignment_debug.log
        echo "---" >> ./tmp/role_assignment_debug.log

        echo "        Exit status: $create_status"

        if [ $create_status -eq 0 ]; then
            echo "    ✓ Assigned role to $principal_id"
        else
            # If the error is the common 'already exists' condition, treat as success silently
            if grep -qi 'RoleAssignmentExists' <<<"$output"; then
                echo "    ✓ Role already assigned to $principal_id (exists)"
            else
                # Show the ENTIRE error output, not just one line
                echo "    ✗ Failed to assign role to $principal_id"
                echo "    Full error output:"
                echo "$output" | sed 's/^/      /'  # Indent each line
                SKIPPED_PRINCIPALS+=("${principal_id}|${role_id}|${scope}|${description}|FULL_OUTPUT_IN_DEBUG_LOG")
            fi
        fi
    done
}

# ============================================================================
# ROLE ASSIGNMENTS - AI SERVICES (aiservices.bicep)
# ============================================================================

echo "1. AI Services Role Assignments"
echo "   Resource: $AI_SERVICES_RESOURCE_ID"

# Cognitive Services OpenAI Contributor - AI Project (CRITICAL for OpenAI calls)
AI_PROJECT_ARRAY=("$AI_PROJECT_PRINCIPAL_ID")
echo "   Assigning Cognitive Services OpenAI Contributor role to AI Project..."
assign_roles_to_principals AI_PROJECT_ARRAY "$COG_SERVICES_OPENAI_CONTRIBUTOR_ROLE_ID" "$AI_SERVICES_RESOURCE_ID" "AI Project" "ServicePrincipal"

# Cognitive Services OpenAI Contributor - All Agents
echo "   Assigning Cognitive Services OpenAI Contributor role to All Agents..."
assign_roles_to_principals AGENTS_PRINCIPAL_IDS "$COG_SERVICES_OPENAI_CONTRIBUTOR_ROLE_ID" "$AI_SERVICES_RESOURCE_ID" "All Agents" "ServicePrincipal"

# Cognitive Services User - Dev Team
echo "   Assigning Cognitive Services User role to Dev Team..."
assign_roles_to_principals DEV_TEAM_PRINCIPAL_IDS "$COG_SERVICES_USER_ROLE_ID" "$AI_SERVICES_RESOURCE_ID" "Dev Team" "User"

echo ""

# ============================================================================
# ROLE ASSIGNMENTS - AI HUB (aihub.bicep)
# ============================================================================

echo "2. AI Hub Role Assignments"
echo "   Resource: $AI_HUB_RESOURCE_ID"

# Azure AI Developer - Dev Team
echo "   Assigning Azure AI Developer role to Dev Team..."
assign_roles_to_principals DEV_TEAM_PRINCIPAL_IDS "$AI_DEVELOPER_ROLE_ID" "$AI_HUB_RESOURCE_ID" "Dev Team" "User"

# Azure AI Developer - All Agents
echo "   Assigning Azure AI Developer role to All Agents..."
assign_roles_to_principals AGENTS_PRINCIPAL_IDS "$AI_DEVELOPER_ROLE_ID" "$AI_HUB_RESOURCE_ID" "All Agents" "ServicePrincipal"

echo ""

# ============================================================================
# ROLE ASSIGNMENTS - AI PROJECT (aihub.bicep)
# ============================================================================

echo "3. AI Project Role Assignments"
echo "   Resource: $AI_PROJECT_RESOURCE_ID"

# Azure AI Developer - Dev Team
echo "   Assigning Azure AI Developer role to Dev Team..."
assign_roles_to_principals DEV_TEAM_PRINCIPAL_IDS "$AI_DEVELOPER_ROLE_ID" "$AI_PROJECT_RESOURCE_ID" "Dev Team" "User"

# Azure AI Developer - All Agents
echo "   Assigning Azure AI Developer role to All Agents..."
assign_roles_to_principals AGENTS_PRINCIPAL_IDS "$AI_DEVELOPER_ROLE_ID" "$AI_PROJECT_RESOURCE_ID" "All Agents" "ServicePrincipal"

echo ""

# ============================================================================
# ROLE ASSIGNMENTS - KEY VAULT (keyVault.bicep)
# ============================================================================

echo "4. Key Vault Role Assignments"
echo "   Resource: $KEYVAULT_RESOURCE_ID"

# Key Vault Secrets Officer - Dev Team
echo "   Assigning Key Vault Secrets Officer role to Dev Team..."
assign_roles_to_principals DEV_TEAM_PRINCIPAL_IDS "$SECRETS_OFFICER_ROLE_ID" "$KEYVAULT_RESOURCE_ID" "Dev Team" "User"

# Key Vault Secrets Officer - All Agents
echo "   Assigning Key Vault Secrets Officer role to All Agents..."
assign_roles_to_principals AGENTS_PRINCIPAL_IDS "$SECRETS_OFFICER_ROLE_ID" "$KEYVAULT_RESOURCE_ID" "All Agents" "ServicePrincipal"

echo ""

# ============================================================================
# ROLE ASSIGNMENTS - STORAGE ACCOUNT (storageAccount.bicep)
# ============================================================================

echo "5. Storage Account Role Assignments"
echo "   Resource: $STORAGE_ACCOUNT_RESOURCE_ID"

# Storage Blob Data Contributor - Dev Team
echo "   Assigning Storage Blob Data Contributor role to Dev Team..."
assign_roles_to_principals DEV_TEAM_PRINCIPAL_IDS "$STORAGE_BLOB_DATA_CONTRIBUTOR_ROLE_ID" "$STORAGE_ACCOUNT_RESOURCE_ID" "Dev Team" "User"

# Storage Blob Data Contributor - All Agents (extra, for flexibility)
echo "   Assigning Storage Blob Data Contributor role to All Agents..."
assign_roles_to_principals AGENTS_PRINCIPAL_IDS "$STORAGE_BLOB_DATA_CONTRIBUTOR_ROLE_ID" "$STORAGE_ACCOUNT_RESOURCE_ID" "All Agents (extra)" "ServicePrincipal"

echo ""

# ============================================================================
# ROLE ASSIGNMENTS - APPLICATION INSIGHTS (appinsights.bicep)
# ============================================================================

if [ -n "$APPINSIGHTS_RESOURCE_ID" ]; then
    echo "6. Application Insights Role Assignments"
    echo "   Resource: $APPINSIGHTS_RESOURCE_ID"
    
    # Monitoring Metrics Publisher - All Agents
    echo "   Assigning Monitoring Metrics Publisher role to All Agents..."
    assign_roles_to_principals AGENTS_PRINCIPAL_IDS "$MONITORING_METRICS_PUBLISHER_ROLE_ID" "$APPINSIGHTS_RESOURCE_ID" "All Agents" "ServicePrincipal"
    
    echo ""
else
    echo "6. Application Insights: Skipped (resource not found)"
    echo ""
fi

# ============================================================================
# SUMMARY
# ============================================================================

echo "=== Role Assignment Creation Complete ==="
echo ""
echo "Next Steps:"
echo "  1. Verify role assignments in Azure Portal"
echo "  2. Dev team can now run: azd hooks run postprovision"
echo "  3. Test application functionality"
echo ""


if [ ${#SKIPPED_PRINCIPALS[@]} -gt 0 ]; then
    echo ""
    echo "⚠ Skipped / Failed Role Assignments (${#SKIPPED_PRINCIPALS[@]})"
    printf "  %-38s  %-38s  %-8s  %s\n" "Principal ID" "Role ID" "ScopeType" "Reason"
    printf "  %-38s  %-38s  %-8s  %s\n" "--------------------------------------" "--------------------------------------" "--------" "------"
    for entry in "${SKIPPED_PRINCIPALS[@]}"; do
        IFS='|' read -r _principal _role _scope _desc _reason <<<"$entry"
        # Derive a short scope type (last provider/type segment) for compact table
        scope_type=$(echo "$_scope" | awk -F'/providers/' '{print $2}' | awk -F'/' '{print $2"/"$3}' 2>/dev/null)
        [ -z "$scope_type" ] && scope_type="(scope)"
        short_reason=$(echo "$_reason" | sed 's/\r//g' | cut -c1-80)
        printf "  %-38s  %-38s  %-8s  %s\n" "$_principal" "$_role" "$scope_type" "$short_reason"
        echo "      Description: $_desc"
        echo "      Full Scope : $_scope"
    done
    echo ""
    echo "You can rerun the script later; failures are often due to propagation (service principal not yet available) or incorrect IDs."
fi
echo "========================================"