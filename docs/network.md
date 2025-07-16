# Network Security Architecture

Healthcare Agent Orchestrator implements a foundational network security architecture that can be enhanced to meet enterprise-grade security requirements for healthcare workloads. This document outlines the current implementation and provides guidance for implementing advanced security features including private App Service deployment with Application Gateway integration.

> [!IMPORTANT]
> The enhanced private architecture options described in this document are recommended for production healthcare environments handling PHI data. The current basic network implementation is suitable for development and testing scenarios.

## Current Network Implementation

The Healthcare Agent Orchestrator deploys with a secure network foundation that includes:

- **Virtual Network (VNet)** isolation with configurable address space (`10.0.0.0/16` default)
- **App Service subnet** with VNet integration (`10.0.1.0/24` default)
- **Service endpoints** for secure access to Azure Key Vault and Web services
- **Public storage accounts** with Azure services bypass for AI Hub and deployment compatibility
- **Network Security Groups (NSGs)** with HTTP/HTTPS inbound rules and Azure services/Internet outbound rules
- **App Service with IP restrictions** allowing access only from Microsoft 365/Teams IP ranges as defined in [Microsoft 365 URLs and IP address ranges](https://learn.microsoft.com/en-us/microsoft-365/enterprise/urls-and-ip-address-ranges?view=o365-worldwide#microsoft-teams) and any additional IPs specified in the `ADDITIONAL_ALLOWED_IPS` parameter set while deploying with azd

> [!NOTE]
> The App Service uses `ipSecurityRestrictionsDefaultAction: 'Deny'` for security. Access is restricted to Microsoft 365/Teams IP ranges and any additional IPs you specify. To add your own IP for development access, use the `ADDITIONAL_ALLOWED_IPS` environment variable during deployment.

### Adding Developer Access

To allow additional IP addresses (such as your development machine) to access the App Service, you can set the `ADDITIONAL_ALLOWED_IPS` environment variable:

```bash
# For a single IP address
azd env set ADDITIONAL_ALLOWED_IPS "203.0.113.100/32"

# For multiple IP addresses or ranges (comma-separated)
azd env set ADDITIONAL_ALLOWED_IPS "203.0.113.100/32,198.51.100.0/24,192.168.1.0/24"

# To remove all additional IPs (only Microsoft 365/Teams ranges will be allowed)
azd env set ADDITIONAL_ALLOWED_IPS ""

# Then redeploy
azd up
```

### Microsoft 365/Teams Integration Considerations

- **IP Restriction Limitations**: The current IP-based approach covers core Teams/M365 services but has limitations with FQDN-dependent services (like `*.teams.microsoft.com`, `login.microsoft.com`). For full functionality, consider Azure Firewall with FQDN rules or the enhanced private architecture with Application Gateway.

### Security Features

- **Network Isolation**: Resources deployed within dedicated virtual network
- **Subnet Delegation**: App Service subnet specifically configured for web applications
- **Service Endpoints**: Secure connectivity to Azure PaaS services without internet routing
- **Traffic Control**: NSG rules for granular inbound and outbound traffic management

### Network Configuration Parameters

The network architecture is fully parameterized and can be customized during deployment. Organizations can modify the following parameters in `main.parameters.json` or during `azd provision`:

**VNet Configuration**:
- `vnetName`: Custom name for the virtual network (auto-generated if not specified)
- `vnetAddressPrefixes`: Array of address prefixes for the VNet (default: `["10.0.0.0/16"]`)
- `networkLocation`: Azure region for network resources should be similar to that as the appservice (defaults to resource group location)

**Subnet Configuration**:
- `subnets`: Array of subnet configurations, each containing:
  - `name`: Subnet name (default: `"appservice-subnet"`)
  - `addressPrefix`: Subnet address range (default: `"10.0.1.0/24"`)
  - `delegation`: Service delegation (default: `"Microsoft.Web/serverFarms"`)
  - `serviceEndpoints`: Array of service endpoints (default: `["Microsoft.KeyVault", "Microsoft.Storage", "Microsoft.Web"]`)
  - `securityRules`: Custom NSG rules for the subnet

**Example Parameter Override**:
```json
{
  "vnetAddressPrefixes": ["172.16.0.0/16"],
  "subnets": [
    {
      "name": "appservice-subnet",
      "addressPrefix": "172.16.1.0/24",
      "delegation": "Microsoft.Web/serverFarms",
      "serviceEndpoints": ["Microsoft.KeyVault", "Microsoft.Storage", "Microsoft.Web"],
      "securityRules": []
    }
  ]
}
```

> [!TIP]
> Organizations should choose non-overlapping address spaces that align with their existing network infrastructure. The default `10.0.0.0/16` range can be modified to avoid conflicts with on-premises networks or other Azure VNets.

## Enhanced Private Architecture Options

For production healthcare environments, organizations may consider upgrading to enterprise-grade security through several architecture enhancements. The following options provide examples of how the current network foundation can be extended to meet more stringent security requirements.

### Example: Private App Service with Application Gateway

**Current Implementation**: App Service is accessible only from Microsoft 365/Teams IP ranges
**Potential Enhancement**: App Service could be made private, accessible only through Application Gateway

**Benefits**:
- Web Application Firewall (WAF) protection against OWASP Top 10 vulnerabilities
- Centralized SSL/TLS termination and certificate management
- Load balancing and traffic distribution capabilities
- Elimination of direct internet access to backend services

> [!NOTE]
> When implementing private App Service deployment, organizations must consider secure developer access methods since direct internet access to the App Service will no longer be available. Common approaches include VPN Gateway (Point-to-Site) with certificate-based authentication, Azure Bastion for browser-based secure access, or private build agents for CI/CD pipeline execution within the VNet.

### Example: Private Endpoints Integration

**Current Implementation**: Service endpoints route traffic over Azure backbone, but services remain publicly accessible
**Potential Enhancement**: Azure services could be accessible via private IP addresses within the VNet

**Benefits**:
- Complete network isolation for all Azure PaaS services
- No internet exposure for Key Vault, Storage, and Cognitive Services
- Private DNS integration for seamless connectivity
- Enhanced compliance with healthcare data protection requirements


### Architecture Components Overview

The following sections outline the key network components and configurations that organizations may need when implementing the enhanced private architecture for their healthcare workloads.

#### Application Gateway Configuration

**Subnet Requirements**:
- Address prefix: `10.0.2.0/24`
- Dedicated subnet for Application Gateway deployment
- No delegation required
- Specific NSG rules for Application Gateway traffic
- Private DNS Zones: Configure  `privatelink.azurewebsites.net` and related zones for private endpoint and vpn name resolution
- Backed Pool Targets: use private endpoint ip's. 

**SSL/TLS Configuration**:
- Frontend HTTPS endpoint with public-facing access
- Backend communication secured between Application Gateway and App Service
- Certificate management integrated with Azure Key Vault

#### Private Endpoints Subnet Configuration

**Subnet Setup**:
- Address prefix: `10.0.3.0/24`
- Dedicated subnet for private endpoint network interfaces
- Network policies configured to support private endpoint deployments

**Private DNS Zones Configuration**:
- Key Vault: `privatelink.vaultcore.azure.net`
- Storage: `privatelink.blob.core.windows.net`
- Cognitive Services: `privatelink.cognitiveservices.azure.com`

#### Developer Access Considerations for Private App Service

When implementing private App Service deployment, organizations must establish secure access methods for development and maintenance activities. The following options address the connectivity requirements:

**VPN Gateway (Point-to-Site)**:
- Subnet: `10.0.4.0/26` (GatewaySubnet)
- Certificate-based authentication
- Point-to-site VPN configuration
- Enables secure remote access for development teams

**Azure Bastion**:
- Subnet: `10.0.5.0/26` (AzureBastionSubnet)
- Browser-based secure access
- Managed jump box service
- No client software installation required
- Access to virtual machines within the VNet for administrative tasks

### Cost Considerations

The enhanced private architecture incurs additional costs for Application Gateway, VPN Gateway, Private Endpoints, and related infrastructure components.

### Implementation Considerations

Organizations may want to consider the following prerequisites when planning enhanced private architecture implementation:

- Azure subscription with appropriate permissions for network resource creation
- SSL certificates for Application Gateway (can be managed through Azure Key Vault)
- Root CA certificate for VPN Gateway setup (if choosing VPN option)
- Updated CI/CD pipelines to support private build agents or secure deployment methods

### Developer Workflow Considerations

**Potential Impact**: Private App Service deployment would change developer access patterns
**Example Mitigation Strategies**:
- Implementing automated CI/CD pipelines to reduce manual access requirements
- Providing VPN access for necessary debugging and troubleshooting
- Using Azure Bastion for secure administrative access
- Establishing clear procedures for emergency access scenarios


> [!WARNING]
> Implementing private App Service deployment would require changes to developer workflows and CI/CD pipelines. Organizations should plan accordingly and ensure proper access methods are configured before disabling public access.

## Next Steps

For detailed implementation guidance, refer to the following resources:

- [Azure Application Gateway documentation](https://docs.microsoft.com/azure/application-gateway/)
- [Private App Service deployment guide](https://docs.microsoft.com/azure/app-service/networking/private-endpoint)
- [Azure Private Endpoints configuration](https://docs.microsoft.com/azure/private-link/private-endpoint-overview)
- [VPN Gateway setup instructions](https://docs.microsoft.com/azure/vpn-gateway/)

The example enhanced private architecture provides a potential foundation for healthcare application hosting in Azure while maintaining compliance with industry standards and regulations.
