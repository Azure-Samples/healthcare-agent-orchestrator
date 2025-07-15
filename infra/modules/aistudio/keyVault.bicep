// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

param location string
param keyVaultName string
param tags object = {}
param grantAccessTo array
param additionalIdentities array = []
param appServiceSubnetId string


var access = [for i in range(0, length(additionalIdentities)): {
  id: additionalIdentities[i]
  type: 'ServicePrincipal'
}]

var grantAccessToUpdated = concat(grantAccessTo, access)

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    createMode: 'default'
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: false
    enableSoftDelete: true
    enableRbacAuthorization: true
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      virtualNetworkRules: [
        {
          id: appServiceSubnetId
          ignoreMissingVnetServiceEndpoint: false
        }
      ]
    }
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
  }
}

resource secretsOfficer 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
}

resource secretsOfficerAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principal in grantAccessToUpdated: if (!empty(principal.id)) {
    name: guid(principal.id, keyVault.id, secretsOfficer.id)
    scope: keyVault
    properties: {
      roleDefinitionId: secretsOfficer.id
      principalId: principal.id
      principalType: principal.type
    }
  }
]


output keyVaultID string = keyVault.id
output keyVaultName string = keyVault.name
output keyVaultEndpoint string = keyVault.properties.vaultUri
