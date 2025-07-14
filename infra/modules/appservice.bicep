// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

param location string
param appServicePlanId string
param appServiceName string
param tags object = {}
param deploymentName string
param deploymentNameReasoningModel string
param openaiEnpoint string
param openaiEndpointReasoningModel string
param aiProjectName string
param msis array = []
param modelEndpoints object
param appBlobStorageEndpoint string
param authClientId string
@secure()
param graphRagSubscriptionKey string
param keyVaultName string
param scenario string
param clinicalNotesSource string
param fhirServiceEndpoint string = ''
param fabricUserDataFunctionEndpoint string = ''
param appServiceSubnetId string

var botIdsArray = [
  for (msi, index) in msis: {
    msi: msi.msiClientID
    name: msi.name
  }
]

var botIds = toObject(botIdsArray, entry => entry.name, entry => entry.msi)

resource graphRagKeyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource graphRagKeyVaultSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: graphRagKeyVault
  name: 'graph-rag-subscription-key'
  properties: {
    value: graphRagSubscriptionKey
  }
}

resource aiProject 'Microsoft.MachineLearningServices/workspaces@2024-04-01-preview' existing = {
  name: aiProjectName
}

// Microsoft 365 IP ranges for IP restrictions (Teams-compatible)
// Based on Microsoft official documentation: https://learn.microsoft.com/en-us/microsoft-365/enterprise/urls-and-ip-address-ranges
var microsoft365IpRanges = [
  // Exchange Online (existing ranges)
  '13.107.6.152/31'
  '13.107.18.10/31' 
  '13.107.128.0/22'
  '23.103.160.0/20'
  '40.96.0.0/13'
  '40.104.0.0/15'
  '52.96.0.0/14'
  '131.253.33.215/32'
  '132.245.0.0/16'
  '150.171.32.0/22'
  '204.79.197.215/32'
  
  // Microsoft Teams (CRITICAL for Teams connectivity)
  '52.112.0.0/14'      // Teams core services & media (ID 11, 12)
  '52.122.0.0/15'      // Teams core services & media (ID 11, 12)
  
  // Microsoft 365 Common & Office Online (for Teams web client)
  '52.108.0.0/14'      // Office Online apps (ID 46)
  '13.107.140.6/32'    // Office Online (ID 46)
  
  // Azure AD Authentication (required for Teams SSO)
  '20.190.128.0/18'    // Azure AD authentication (ID 56)
  '40.126.0.0/18'      // Azure AD authentication (ID 56)
  '20.20.32.0/19'      // Azure AD authentication (ID 56)
  '20.231.128.0/19'    // Azure AD authentication (ID 56)
]

var ipSecurityRestrictions = [
  for (ipRange, index) in microsoft365IpRanges: {
    ipAddress: ipRange
    action: 'Allow'
    priority: 1000 + index
    name: 'AllowMicrosoft365-${index}'
    description: 'Allow Microsoft 365 IP range ${ipRange}'
  }
]

resource backend 'Microsoft.Web/sites@2023-12-01' = {
  name: appServiceName
  location: location
  tags: union(tags, { 'azd-service-name': 'healthcare-agent-orchestrator-app' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: toObject(msis, entry => entry.msiID, entry => {})
  }
  properties: {
    serverFarmId: appServicePlanId
    httpsOnly: true
    virtualNetworkSubnetId: appServiceSubnetId
    siteConfig: {
      httpLoggingEnabled: true
      logsDirectorySizeLimit: 35
      publicNetworkAccess: 'Enabled'
      ipSecurityRestrictionsDefaultAction: 'Deny'
      ipSecurityRestrictions: ipSecurityRestrictions
      scmIpSecurityRestrictionsDefaultAction: 'Allow'
      http20Enabled: true
      linuxFxVersion: 'PYTHON|3.12'
      webSocketsEnabled: true
      appCommandLine: 'gunicorn app:app'
      alwaysOn: true
      vnetRouteAllEnabled: true
    }
    keyVaultReferenceIdentity: msis[0].msiID
  }
}

resource authSettingsConfig 'Microsoft.Web/sites/config@2024-04-01' = if (authClientId != '') {
  parent: backend
  name: 'authsettingsV2'
  properties: {
    globalValidation: {
      requireAuthentication: true
      excludedPaths: [for msi in msis: '/api/${msi.name}/messages']
      redirectToProvider: 'azureActiveDirectory'
      unauthenticatedClientAction: 'RedirectToLoginPage'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: authClientId
          openIdIssuer: 'https://sts.windows.net/${tenant().tenantId}'
        }
        validation: {
          allowedAudiences: ['https://${backend.properties.defaultHostName}/.auth/login/aad/callback', '']
        }
      }
    }
  }
}

resource backEndNameSiteConfig 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: backend
  name: 'appsettings'
  kind: 'string'
  properties: {
    MicrosoftAppType: 'UserAssignedMSI'
    AZURE_CLIENT_ID: msis[0].msiClientID
    MicrosoftAppTenantId: tenant().tenantId
    AZURE_AI_PROJECT_CONNECTION_STRING: '${split(aiProject.properties.discoveryUrl, '/')[2]};${subscription().subscriptionId};${resourceGroup().name};${aiProjectName}'
    AZURE_OPENAI_API_ENDPOINT: openaiEnpoint
    AZURE_OPENAI_ENDPOINT: openaiEnpoint
    AZURE_OPENAI_REASONING_MODEL_ENDPOINT: openaiEndpointReasoningModel
    AZURE_OPENAI_DEPLOYMENT_NAME: deploymentName
    AZURE_OPENAI_DEPLOYMENT_NAME_REASONING_MODEL: deploymentNameReasoningModel
    APP_BLOB_STORAGE_ENDPOINT: appBlobStorageEndpoint
    SCM_DO_BUILD_DURING_DEPLOYMENT: 'true'
    ENABLE_ORYX_BUILD: 'true'
    DEBUG: 'true'
    BOT_IDS: string(botIds)
    HLS_MODEL_ENDPOINTS: string(modelEndpoints)
    BACKEND_APP_HOSTNAME: backend.properties.defaultHostName
    GRAPH_RAG_SUBSCRIPTION_KEY: '@Microsoft.KeyVault(VaultName=${graphRagKeyVault.name};SecretName=${graphRagKeyVaultSecret.name})'
    SCENARIO: scenario
    CLINICAL_NOTES_SOURCE: clinicalNotesSource
    FHIR_SERVICE_ENDPOINT: fhirServiceEndpoint
    FABRIC_USER_DATA_FUNCTION_ENDPOINT: fabricUserDataFunctionEndpoint
  }
}

// VNet integration for App Service
// VNet integration is now handled directly in the App Service resource properties

output backendHostName string = backend.properties.defaultHostName
output botIds object = botIds
output modelEndpoints object = modelEndpoints
