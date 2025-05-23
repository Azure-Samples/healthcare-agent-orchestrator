param (
    [string]$directory,
    [string]$chatOrMeeting,                              
    [string]$tenantId                                    
)

# ---------------------------------------------------------------------
# Resolve tenantId (if not supplied)
# ---------------------------------------------------------------------
if (-not $tenantId) {
    try {
        $tenantId = (Get-AzContext -ErrorAction Stop).Tenant.Id
        Write-Host "Using tenantId: $tenantId"
    } catch {
        Write-Error "Unable to determine tenantId from the current Az context. Pass -tenantId explicitly."
        exit 1
    }
}

# ---------------------------------------------------------------------
# Derive teamsChatId from chatOrMeeting
#   • Accepts raw chatId ("19:...@thread.v2") or any Teams URL
#   • Handles URL-encoded links
# ---------------------------------------------------------------------
$chatPattern = '19:[^/]+@thread\.v2'
$teamsChatId  = $null

# Direct chatId supplied?
if ($chatOrMeeting -match "^$chatPattern$") {
    $teamsChatId = $chatOrMeeting
    Write-Host "Using supplied teamsChatId: $teamsChatId"
} else {
    # Assume it is a link – try to extract the ID (supports encoded links)
    $decoded = [uri]::UnescapeDataString($chatOrMeeting)
    $teamsChatId = [regex]::Match($decoded, $chatPattern).Value

    if ($teamsChatId) {
        Write-Host "Extracted teamsChatId from link: $teamsChatId"
    } else {
        Write-Error "Unable to determine teamsChatId from input."
        exit 1
    }
}

# ---------------------------------------------------------------------
# Get the auth token
# ---------------------------------------------------------------------
if (-not (Get-Module -ListAvailable -Name Az.Accounts)) {
    Write-Host "Az.Accounts module is not loaded. Loading module..."
    Import-Module Az.Accounts
} else {
    Write-Host "Az.Accounts module is already loaded."
}

$authToken = (ConvertFrom-SecureString -AsPlainText (Get-AzAccessToken -AsSecureString -ResourceUrl "https://teams.microsoft.com" -Tenant $tenantId).Token)

# Make a POST call to get regionGtms/appService
$authzUrl = "https://teams.microsoft.com/api/authsvc/v1.0/authz"
$authzHeaders = @{
    Authorization = "Bearer $authToken"
    "Content-Type" = "application/json"
}

$response = Invoke-RestMethod -Method Post -Uri $authzUrl -Headers $authzHeaders -UseBasicParsing
$appService = $null

if ($response -and $response.regionGtms -and $response.regionGtms.appService) {
    $appService = $response.regionGtms.appService
    Write-Host "Extracted appService: $appService"
} else {
    Write-Error "Failed to extract regionGtms/appService from the response."
    exit 1
}

# Iterate over all zip files in the directory
Get-ChildItem -Path $directory -Filter *.zip | ForEach-Object {
    $zipFile = $_.FullName

    # Prepare the POST request
    $url = "$appService/beta/chats/$teamsChatId/apps/definitions/appPackage"
    $headers = @{
        Authorization = "Bearer $authToken"
        "Content-Type" = "application/x-zip-compressed"     
    }

    # Perform the POST request
    Invoke-RestMethod -Method Post -Uri $url -Headers $headers -UseBasicParsing -InFile $zipFile
}