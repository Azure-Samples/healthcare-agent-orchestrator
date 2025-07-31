# Access Control

> For network access control, see [Network Security Architecture](./network.md)

Healthcare Agent Orchestrator provides tenant-level and user-level access control using this [middleware](https://github.com/Azure-Samples/healthcare-agent-orchestrator/blob/main/src/bots/access_control_middleware.py). By default, all tenants and users are allowed to use the deployed agents in Teams.

To restrict access to agents, access control can be configured using environment variables. Tenant ID and user ID can be looked up in [Microsoft Entra](https://entra.microsoft.com).

- **ADDITIONAL_ALLOWED_TENANT_IDS**: A comma-separated list of tenant IDs to allow.
- **ADDITIONAL_ALLOWED_USER_IDS**: A comma-separated list of user IDs to allow.

If user is not authorized to access an agent, the agent will respond with `You are not authorized to access this agent.`. Check AppService log for the reason of denied access.

> [!IMPORTANT]
> The user who deploys Healthcare Agent Orchestrator and the tenant where it's deployed are always allowed.

## Sample Configurations
This section provides sample configurations for various scenarios of access control.

### Allow All
Allow all Teams users from all tenants.
> [!IMPORTANT]
> This is the default configuration
```ps
azd env set ADDITIONAL_ALLOWED_TENANT_IDS "*"
azd env set ADDITIONAL_ALLOWED_USER_IDS "*"

# deploy changes
azd up
```

### Allow Single User
Allow only the deployer and the tenant of the Healthcare Agent Orchestrator deployment in Azure.
```ps
azd env set ADDITIONAL_ALLOWED_TENANT_IDS ""
azd env set ADDITIONAL_ALLOWED_USER_IDS ""

# deploy changes
azd up
```

### Allow All Users from Single Tenant
Allow all users from the tenant of the the Healthcare Agent Orchestrator deployment in Azure.

```ps
azd env set ADDITIONAL_ALLOWED_TENANT_IDS ""
azd env set ADDITIONAL_ALLOWED_USER_IDS "*"

# deploy changes
azd up
```

### Allow Selected Users from Single Tenant
Allow selected users from the tenant of the the Healthcare Agent Orchestrator deployment in Azure.

```ps
azd env set ADDITIONAL_ALLOWED_TENANT_IDS ""
azd env set ADDITIONAL_ALLOWED_USER_IDS "ed75b98f-843a-4564-80a8-5d605cc3a269,79b9c23f-ddb5-4668-93d0-de9d28beb1ae"

# deploy changes
azd up
```

### Allow Selected Users from Selected Tenants
Allow selected users from selected tenants.

```ps
azd env set ADDITIONAL_ALLOWED_TENANT_IDS "4353a697-7b67-4853-b28b-398738f6bba3,0358baed-eea8-4b45-a23c-97844d8e0aee"
azd env set ADDITIONAL_ALLOWED_USER_IDS "ed75b98f-843a-4564-80a8-5d605cc3a269,79b9c23f-ddb5-4668-93d0-de9d28beb1ae"

# deploy changes
azd up
```
