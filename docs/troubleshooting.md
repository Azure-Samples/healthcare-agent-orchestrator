# Troubleshooting

## Deploy the Infrastructure

### Operation cannot be completed without additional quota

The deployment might fail because of a lack of quota for the App Service Plan. In that case, you may see an error such as:
> Operation cannot be completed without additional quota

Try switching the location of the app service plan to a different region using the following command:
> azd env set AZURE_APPSERVICE_LOCATION canadacentral

Then run `azd up` again.

### Post Provision Hook Failed with Exit Code 127 (Dev Container Issue)

When running `azd up` in a dev container environment, you may encounter the following error:

```
post provision hook failed with exit code : '127' 
Path: '/tmp/azd-postprovision-##########.sh'
```

This error typically occurs due to **line ending differences (CRLF vs LF)** between Windows and Unix systems when working in dev containers.

#### Root Cause
The issue happens when:
- Git is configured with `core.autocrlf = true` (common on Windows)
- Shell scripts get checked out with Windows line endings (CRLF)
- Dev container tries to execute scripts with CRLF endings on a Unix system
- Unix systems expect LF line endings for shell scripts

#### Solution 1: Fix Git Configuration

1. **Check your current Git configuration:**
   ```bash
   git config core.autocrlf
   ```

2. **If the output is `true`, change it to `input`:**
   ```bash
   git config --global core.autocrlf input
   ```

3. **Re-clone the repository to get correct line endings:**
   ```bash
   cd ..
   rm -rf healthcare-agent-orchestrator
   git clone https://github.com/Azure-Samples/healthcare-agent-orchestrator.git
   cd healthcare-agent-orchestrator
   ```

4. **Run the deployment again:**
   ```bash
   azd up
   ```

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
