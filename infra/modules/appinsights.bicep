@description('Name of the Application Insights resource')
param appInsightsName string
@description('Location for Application Insights')
param location string = resourceGroup().location
@description('Tags for the resource')
param tags object = {}
param grantAccessTo array = []

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    RetentionInDays: 90
    DisableLocalAuth: true
  }
  tags: tags
}

resource monitoringMetricsPublisherRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: '3913510d-42f4-4e42-8a64-420c390055eb'
}

resource AppInsightsLoggingAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principal in grantAccessTo: if (!empty(principal.id)) {
    name: guid(principal.id, appInsights.id, monitoringMetricsPublisherRole.id)
    scope: appInsights
    properties: {
      roleDefinitionId: monitoringMetricsPublisherRole.id
      principalId: principal.id
      principalType: principal.type
    }
  }
]


output connectionString string = appInsights.properties.ConnectionString
