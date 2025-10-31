// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

param location string
param appBackend string
param bots array
param sku string = 'F0'
param kind string = 'azurebot'
param tags object = {}

var icons = {
  Orchestrator: loadFileAsBase64('../botIcons/Orchestrator.png')
  PatientHistory: loadFileAsBase64('../botIcons/PatientHistory.png')
  Radiology: loadFileAsBase64('../botIcons/Radiology.png')
  ReportCreation: loadFileAsBase64('../botIcons/ReportCreation.png')
  ClinicalGuidelines: loadFileAsBase64('../botIcons/ClinicalGuidelines.png')
  PatientStatus: loadFileAsBase64('../botIcons/PatientStatus.png')
  ClinicalTrials: loadFileAsBase64('../botIcons/ClinicalTrials.png')
}

resource botservice 'Microsoft.BotService/botServices@2022-09-15' = [
  for msi in bots: {
    name: '${msi.name}-${uniqueString(resourceGroup().id)}'
    location: location
    tags: tags
    sku: {
      name: sku
    }
    kind: kind
    properties: {
      displayName: msi.name
      endpoint: 'https://${appBackend}/api/${msi.name}/messages'
      msaAppMSIResourceId: msi.msiID
      msaAppId: msi.msiClientID
      msaAppType: 'UserAssignedMSI'
      msaAppTenantId: tenant().tenantId
      publicNetworkAccess: 'Enabled'
      disableLocalAuth: true
      iconUrl: 'data:image/png;base64,${icons[?msi.name] ?? icons.Orchestrator}'
    }
  }
]

resource teamsChannel 'Microsoft.BotService/botServices/channels@2022-09-15' = [
  for (msi, index) in bots: {
    parent: botservice[index]
    name: 'MsTeamsChannel'
    location: location
    properties: {
      channelName: 'MsTeamsChannel'
      properties: {
        isEnabled: true
        acceptedTerms: true
        enableCalling: true
      }
    }
  }
]
