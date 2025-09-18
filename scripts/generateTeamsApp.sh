#!/usr/bin/env sh
# SYNOPSIS
# Generates a set of Teams app packages based on the provided manifest file directory.

# PARAMETERS
# manifestFileDirectory: Specifies the directory where the Teams app manifest file is located.
# output: Specifies the output directory where the generated Teams app packages will be saved.

# EXAMPLE
# ./generateTeamsApp.sh -manifestFileDirectory "/path/to/manifest" -output "/path/to/output"
# This example generates a set of Teams app packages using the manifest file located in "/path/to/manifest" and saves the packages to "/path/to/output".
set -e

usage() {
    echo "Usage: $0 -manifestFileDirectory <manifestFileDirectory> -output <output>"
    exit 1
}

while [ "$#" -gt 0 ]; do
    case $1 in
        -manifestFileDirectory) manifestFileDirectory="$2"; shift ;;
        -output) output="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; usage ;;
    esac
    shift
done

if [ -z "$manifestFileDirectory" ] || [ -z "$output" ]; then
    usage
fi

# Delete the directory if it exists
if [ -d "$output" ]; then
    rm -rf "$output"
fi

# Ensure the output directory is created
mkdir -p "$output"

scriptDirectory="$(cd "$(dirname "$0")" && pwd)"
rootDirectory="$(dirname "$scriptDirectory")"

azure_bots=$(azd env get-value AZURE_BOTS)

# Load Azure Bots content from environment variable
azureBotsContent=$(echo "$azure_bots" | jq -c '.[]')

# Define the manifest file path
manifestFilePath="$manifestFileDirectory/manifest.json"

# Load the manifest file content
manifestContent=$(cat "$manifestFilePath")
# Check if zip is installed, if not install it

if ! command -v zip > /dev/null; then
    echo "zip is not installed. Installing zip..."
    echo "install zip and retry"
    exit 1
fi

# Iterate over each bot in the azureBotsContent array
echo "$azureBotsContent" | while IFS= read -r bot; do
    botName=$(echo "$bot" | jq -r '.name')
    botId=$(echo "$bot" | jq -r '.botId')
    botOutputDirectory="$output/$botName"
    cp -r "$manifestFileDirectory" "$botOutputDirectory"
    if [ -f "$rootDirectory/infra/botIcons/$botName.png" ]; then
        cp "$rootDirectory/infra/botIcons/$botName.png" "$botOutputDirectory"
    else
        cp "$rootDirectory/infra/botIcons/Orchestrator.png" "$botOutputDirectory/$botName.png"
    fi
    # Replace the id in the manifest content with the bot id
    updatedManifestContent=$(echo "$manifestContent" | jq --arg botId "$botId" --arg botName "$botName" '
        .id = $botId |
        .bots[0].botId = $botId |
        .name.short = $botName |
        .name.full = $botName |
        .description.short = $botName |
        .description.full = $botName |
        .icons.outline = ($botName + ".png")  |
        .icons.color = ($botName + ".png") |
        .webApplicationInfo.id = $botId |
        .webApplicationInfo.resource = "api://botid-$botId"
    ')

    # Define the new manifest file path
    newManifestFilePath="$botOutputDirectory/manifest.json"

    # Save the updated manifest content to the new location
    echo "$updatedManifestContent" > "$newManifestFilePath"

    # Create a zip file of the botOutputDirectory contents
    zipFilePath="$output/$botName.zip"
    echo "Creating zip file from directory: $botOutputDirectory"
    echo "Zip file will be saved to: $zipFilePath"
    zip -j $zipFilePath $botOutputDirectory/*
done