// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

@description('Location for the network resources')
param location string

@description('Name of the virtual network')
param vnetName string

@description('Virtual network address prefixes')
param vnetAddressPrefixes array = ['10.0.0.0/16']

@description('Subnet configurations for the virtual network')
param subnets array = [
  {
    name: 'appservice-subnet'
    addressPrefix: '10.0.1.0/24'
    delegation: 'Microsoft.Web/serverFarms'
    serviceEndpoints: ['Microsoft.KeyVault', 'Microsoft.Storage', 'Microsoft.Web']
    securityRules: []
  }
]

@description('Tags for network resources')
param tags object = {}

// Network Security Groups for subnets
resource nsg 'Microsoft.Network/networkSecurityGroups@2023-09-01' = [for subnet in subnets: {
  name: '${subnet.name}-nsg'
  location: location
  tags: tags
  properties: {
    securityRules: subnet.securityRules
  }
}]

// Virtual Network
resource vnet 'Microsoft.Network/virtualNetworks@2023-09-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: vnetAddressPrefixes
    }
  }
}

// Subnets
resource subnet 'Microsoft.Network/virtualNetworks/subnets@2023-09-01' = [for (subnet, i) in subnets: {
  parent: vnet
  name: subnet.name
  properties: {
    addressPrefix: subnet.addressPrefix
    networkSecurityGroup: {
      id: nsg[i].id
    }
    delegations: subnet.delegation != '' ? [
      {
        name: subnet.delegation
        properties: {
          serviceName: subnet.delegation
        }
      }
    ] : []
    serviceEndpoints: [for endpoint in subnet.serviceEndpoints: {
      service: endpoint
      locations: [
        location
      ]
    }]
  }
}]

output vnetId string = vnet.id
output vnetName string = vnet.name
output subnetIds array = [for i in range(0, length(subnets)): subnet[i].id]
output subnetNames array = [for subnet in subnets: subnet.name]
output appServiceSubnetId string = subnet[0].id // First subnet is assumed to be app service subnet
output nsgIds array = [for i in range(0, length(subnets)): nsg[i].id]
