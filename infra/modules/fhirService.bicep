param workspaceName string
param fhirServiceName string
param tenantId string
param grantAccessTo array
param tags object = {}

var loginURL = environment().authentication.loginEndpoint
var authority = '${loginURL}${tenantId}'
var audience = 'https://${fhirServiceName}.fhir.azurehealthcareapis.com'

var mergedTags = union({
  FhirServiceTemplate: 'FHIRServiceDeployment'
}, tags)

resource ahdsWorkspace 'Microsoft.HealthcareApis/workspaces@2021-06-01-preview' = {
  name: workspaceName
  location: resourceGroup().location
  tags: mergedTags
}

resource fhirService 'Microsoft.HealthcareApis/workspaces/fhirservices@2022-06-01' = {
  parent: ahdsWorkspace
  name: fhirServiceName
  location: resourceGroup().location
  kind: 'fhir-R4'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    accessPolicies: []
    authenticationConfiguration: {
      authority: authority
      audience: audience
      smartProxyEnabled: false
    }
  }
  tags: mergedTags
}

resource fhirDataReader 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: '4c8d0bbc-75d3-4935-991f-5f3c56d81508'
}

resource fhirDataReaderAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principal in grantAccessTo: if (!empty(principal.id)) {
    name: guid(principal.id, fhirService.id, fhirDataReader.id)
    scope: fhirService
    properties: {
      roleDefinitionId: fhirDataReader.id
      principalId: principal.id
      principalType: principal.type
    }
  }
]

output endpoint string = audience
