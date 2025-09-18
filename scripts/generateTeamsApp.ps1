<#
.SYNOPSIS
Generates a Teams app package based on the provided manifest file directory.

.PARAMETER manifestFileDirectory
Specifies the directory where the Teams app manifest file is located.

.PARAMETER output
Specifies the output directory where the generated Teams app package will be saved.

.EXAMPLE
.\generateTeamsApp.ps1 -manifestFileDirectory "C:\path\to\manifest" -output "C:\path\to\output"
This example generates a Teams app package using the manifest file located in "C:\path\to\manifest" and saves the package to "C:\path\to\output".
#>
param (
    [string]$manifestFileDirectory,
    [string]$output
)
# Delete the directory if it exists
if (Test-Path -Path $output) {
    Remove-Item -Path $output -Recurse -Force
}
# Ensure the output directory is created
if (-not (Test-Path -Path $output)) {
    New-Item -Path $output -ItemType Directory | Out-Null
}

$scriptDirectory = Split-Path -Parent -Path $MyInvocation.MyCommand.Definition
$rootDirectory = Split-Path -Parent -Path $scriptDirectory

$azure_bots = azd env get-value AZURE_BOTS

# Load Azure Bots content from environment variable
$azureBotsContent = $azure_bots | ConvertFrom-Json

# Define the manifest file path
$manifestFilePath = Join-Path -Path $manifestFileDirectory -ChildPath "manifest.json"

# Load the manifest file content
$manifestContent = Get-Content -Path $manifestFilePath -Raw | ConvertFrom-Json

# Iterate over each bot in the azureBotsContent array
foreach ($bot in $azureBotsContent) {
    $botOutputDirectory = Join-Path -Path $output -ChildPath $bot.name
    Copy-Item -Path $manifestFileDirectory -Destination $botOutputDirectory -Recurse -Force
    $iconPath = Join-Path -Path "$rootDirectory\infra\botIcons" -ChildPath "$($bot.name).png"
    if (Test-Path -Path $iconPath) {
        Copy-Item -Path $iconPath -Destination $botOutputDirectory -Force
    } else {
        $iconPath = Join-Path -Path "$rootDirectory\infra\botIcons" -ChildPath "Orchestrator.png"
        Copy-Item -Path $iconPath -Destination "$botOutputDirectory\$($bot.name).png" -Force
    }

    # Replace the id in the manifest content with the bot id
    $manifestContent.id = $bot.botId
    $manifestContent.bots[0].botId = $bot.botId
    $manifestContent.name.short = $bot.name
    $manifestContent.name.full = $bot.name
    $manifestContent.description.short = $bot.name
    $manifestContent.description.full = $bot.name    
    $manifestContent.icons.color = $bot.name + ".png"
    $manifestContent.icons.outline = $bot.name + ".png"
    $manifestContent.webApplicationInfo.id = $bot.botId
    $manifestContent.webApplicationInfo.resource = "api://botid-$($bot.botId)"
    
    # Define the new manifest file path
    $newManifestFilePath = Join-Path -Path $botOutputDirectory -ChildPath "manifest.json"

    # Save the updated manifest content to the new location
    $manifestContent | ConvertTo-Json -Depth 10 | Set-Content -Path $newManifestFilePath

    # Create a zip file of the botOutputDirectory contents
    $zipFilePath = Join-Path -Path $output -ChildPath "$($bot.name).zip"
    Add-Type -AssemblyName 'System.IO.Compression.FileSystem'

    $zipFilePath = Join-Path -Path $rootDirectory -ChildPath $zipFilePath
    $botOutputDirectory = Join-Path -Path $rootDirectory -ChildPath $botOutputDirectory
    Write-Host "Creating zip file from directory: $botOutputDirectory"
    Write-Host "Zip file will be saved to: $zipFilePath"
    [System.IO.Compression.ZipFile]::CreateFromDirectory($botOutputDirectory, $zipFilePath)
}