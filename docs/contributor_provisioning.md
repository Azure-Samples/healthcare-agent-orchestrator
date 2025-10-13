# Provisioning and deploying HAO with `Contributor` role

For the following guide, one should need only

This guide assumes the Developer deploying the code has `Contributor` and `Storage Blob Contributor` scoped to the target Resource Group. The Cloud team must have `Owner` or `User Access Administrator` for creating Role Assignments.


## Steps:

Provisioning and deployment of the code is split into 3 phases: *General provisioning*, *Role assignment creation*, and *Post-provisioning and Deployment*.

1. Search for `roleAssignments` in the `infra` folder, and comment out all entries found. Example:
    ```bicep
    // resource AppInsightsLoggingAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
    //   for principal in grantAccessTo: if (!empty(principal.id)) {
    //     name: guid(principal.id, appInsights.id, monitoringMetricsPublisherRole.id)
    //     scope: appInsights
    //     properties: {
    //       roleDefinitionId: monitoringMetricsPublisherRole.id
    //       principalId: principal.id
    //       principalType: principal.type
    //     }
    //   }
    // ]
    ```
1. By default, Bicep linting does not allow unused variables, so we must add the following `bicepconfig.json` to the project root:
    ```json
    {
        "analyzers": {
            "core": {
                "rules": {
                    "no-unused-vars": {
                    "level": "off"
                    },
                    "no-unused-params": {
                    "level": "off"
                    },
                    "no-unused-existing-resources": {
                    "level": "off"
                    }
                }
                }
            }
    }
    ```
1. Follow documentation until you complete ``Step 2: Create an `azd` Environment & Set Variables``.
1. Start the provisioning step by running:
    ```
    azd provision
    ```
    - If an error occurs with the Bicep template validation, you may need to manually set some variables, such as  `AZURE_LOCATION`.

    - The script **should** end with an error like the following:
        <details>
        <summary>Post-provision hook - Permission error.</summary>
        ```
        ERROR: failed running post hooks: 'postprovision' hook failed with exit code: '1', Path: '/tmp/azd-postprovision-3418865824.sh'. : exit code: 1, stdout: Creating zip file from directory: ./output/Orchestrator
        Zip file will be saved to: ./output/Orchestrator.zip
        adding: Orchestrator.png (stored 0%)
        adding: manifest.json (deflated 64%)
        Creating zip file from directory: ./output/PatientHistory
        Zip file will be saved to: ./output/PatientHistory.zip
        adding: PatientHistory.png (stored 0%)
        adding: manifest.json (deflated 64%)
        Creating zip file from directory: ./output/Radiology
        Zip file will be saved to: ./output/Radiology.zip
        adding: Radiology.png (stored 0%)
        adding: manifest.json (deflated 64%)
        Creating zip file from directory: ./output/PatientStatus
        Zip file will be saved to: ./output/PatientStatus.zip
        adding: PatientStatus.png (stored 0%)
        adding: manifest.json (deflated 64%)
        Creating zip file from directory: ./output/ClinicalGuidelines
        Zip file will be saved to: ./output/ClinicalGuidelines.zip
        adding: ClinicalGuidelines.png (stored 0%)
        adding: manifest.json (deflated 65%)
        Creating zip file from directory: ./output/ReportCreation
        Zip file will be saved to: ./output/ReportCreation.zip
        adding: ReportCreation.png (stored 0%)
        adding: manifest.json (deflated 65%)
        Creating zip file from directory: ./output/ClinicalTrials
        Zip file will be saved to: ./output/ClinicalTrials.zip
        adding: ClinicalTrials.png (stored 0%)
        adding: manifest.json (deflated 64%)
        Creating zip file from directory: ./output/MedicalResearch
        Zip file will be saved to: ./output/MedicalResearch.zip
        adding: MedicalResearch.png (stored 0%)
        adding: manifest.json (deflated 64%)
        Creating zip file from directory: ./output/magentic
        Zip file will be saved to: ./output/magentic.zip
        adding: magentic.png (stored 0%)
        adding: manifest.json (deflated 64%)
        Deleting patient data for patient_4
        Uploading patient data from /home/lschettini/dev/microsoft/medbench/healthcare-agent-orchestrator/infra/patient_data/patient_4
        , stderr: WARNING: your version of azd is out of date, you have 1.17.0 and the latest version is 1.19.0

        To update to the latest version, run:
        curl -fsSL https://aka.ms/install-azd.sh | bash

        If the install script was run with custom parameters, ensure that the same parameters are used for the upgrade. For advanced install instructions, see: https://aka.ms/azd/upgrade/linux
        WARNING: your version of azd is out of date, you have 1.17.0 and the latest version is 1.19.0

        To update to the latest version, run:
        curl -fsSL https://aka.ms/install-azd.sh | bash

        If the install script was run with custom parameters, ensure that the same parameters are used for the upgrade. For advanced install instructions, see: https://aka.ms/azd/upgrade/linux
        ERROR: 
        You do not have the required permissions needed to perform this operation.
        Depending on your operation, you may need to be assigned one of the following roles:
            "Storage Blob Data Owner"
            "Storage Blob Data Contributor"
            "Storage Blob Data Reader"
            "Storage Queue Data Contributor"
            "Storage Queue Data Reader"
            "Storage Table Data Contributor"
            "Storage Table Data Reader"

        If you want to use the old authentication method and allow querying for the right account key, please use the "--auth-mode" parameter and "key" value.
                            
        ERROR: 
        You do not have the required permissions needed to perform this operation.
        Depending on your operation, you may need to be assigned one of the following roles:
            "Storage Blob Data Owner"
            "Storage Blob Data Contributor"
            "Storage Blob Data Reader"
            "Storage Queue Data Contributor"
            "Storage Queue Data Reader"
            "Storage Table Data Contributor"
            "Storage Table Data Reader"

        If you want to use the old authentication method and allow querying for the right account key, please use the "--auth-mode" parameter and "key" value.
        ```
        </details>

1. Run [scripts/createRoleAssignments.sh](../scripts/createRoleAssignments.sh)
    - The script creates the same role assignments as defined in the `bicep` files, which were commented out in Step 1. of this guide.
    - The Cloud team must fill the `DEV_TEAM_PRINCIPAL_IDS` array with the principal ID of all users that should have access to the cloud resources.
        - To get a user's principal ID, run: `az ad user show --id <user@domain.com> --query id -o tsv`.
        - The `DEV_TEAM_PRINCIPAL_IDS` should look like this `DEV_TEAM_PRINCIPAL_IDS=("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" "ffffffff-0000-1111-2222-333333333333")`
        - The `DEV_TEAM_PRINCIPAL_IDS` will get the following roles:
            - Cognitive Services User;
            - Azure AI Developer (scoped to both AI Hub and AI Project resources);
            - Key Vault Secrets Officer;
            - Storage Blob Contributor.
    - In case the Cloud team running the script does not have access to the same `azd` environment, those following this guide must change the `HAO_RESOURCE_GROUP` variable accordingly.
        - Example: `HAO_RESOURCE_GROUP=rg-hao`
    
    > [!IMPORTANT]
    > When Managed Identities are created, Azure triggers the creation of a Service Principal, which may take some time until it is replicated globally. Role Assignments are only possible after the Service Principal creation has finished. See also: [Assigning a role to a new principal sometimes fails](https://learn.microsoft.com/en-us/azure/role-based-access-control/troubleshooting?tabs=bicep#symptom---assigning-a-role-to-a-new-principal-sometimes-fails). 

1. Run post-provision hook:
    ```bash
    azd hooks run postprovision
    ```

    For this command, you will need the `Storage Blob Contributor` role, which was assigned to all users in `DEV_TEAM_PRINCIPAL_IDS` by the previous step.

1. Run `azd deploy` to deploy the application.

1. Follow steps 4, 5 and 6 from the [README.md](./README.md).