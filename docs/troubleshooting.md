# Troubleshooting

## Deploy the Infrastructure

### Operation cannot be completed without additional quota

The deployment might fail because of a lack of quota for the App Service Plan. In that case, you may see an error such as:
> Operation cannot be completed without additional quota

Try switching the location of the app service plan to a different region using the following command:
> azd env set AZURE_APPSERVICE_LOCATION canadacentral

Then run `azd up` again.

## Teams

### Install the Agents in Microsoft Teams

#### Authentication errors on Windows

If you encounter authentication errors, you can manually obtain a token:

> [!NOTE]
> This command should be run on the same PC where you typically use Microsoft Teams.

**Bash/Unix:**

```sh
authToken=$(az account get-access-token \
    --resource "https://teams.microsoft.com" \
    --tenant "$tenantId" --query accessToken -o tsv)
```

**PowerShell/Windows:**

```powershell
$authToken = (Get-AzAccessToken -ResourceUrl "https://teams.microsoft.com" -Tenant $tenantId).Token
```

#### Determining tenant ID on Windows

If you are getting an error `Write-Error: Unable to determine tenantId from the current Az context. Pass -tenantId explicitly.`, try running the following command first to connect your Azure account to the current Powershell session.

```powershell
Connect-AzAccount
```

You may need to install the module first with the following command

```powershell
Install-Module az.accounts
```
