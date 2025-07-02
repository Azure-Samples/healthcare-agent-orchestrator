// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

param aiServicesName string
param modelName string
param modelVersion string
param modelCapacity int = 10
param modelSku string

resource aiServices 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: aiServicesName

  resource gptdeployment 'deployments' = if (startsWith(modelName, 'gpt')) {
    name: modelName
    properties: {
      model: {
        format: 'OpenAI'
        name: modelName
        version: modelVersion
      }
    }
    sku: {
      capacity: modelCapacity
      name: modelSku
    }
  }
}

output modelName string = aiServices::gptdeployment.name
output modelVersion string = aiServices::gptdeployment.properties.model.version
