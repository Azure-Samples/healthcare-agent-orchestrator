## Microsoft Fabric + healthcare data solutions (HDS) Integration

### Overview
This user guide provides instructions for integrating AI agents with [healthcare data solutions (HDS) on Microsoft Fabric](https://learn.microsoft.com/en-us/industry/healthcare/healthcare-data-solutions/overview). Microsoft Fabric provides a comprehensive ecosystem for data integration, data engineering, real-time analytics, data science, and business intelligence. Healthcare data solutions (HDS) is built on Fabric and provides several capabilities making it easy to manage and analyze your multi-modal healthcare data. 

Healthcare data solutions (HDS) supports both FHIR and OMOP, but will use FHIR in this example. The changes required to use FHIR are trivial and will be covered briefly in this doc.

### What is healthcare data solutions (HDS) on Fabric?

Healthcare Data Solutions (HDS) in Microsoft Fabric is an end-to-end analytics SaaS platform that enables you to ingest, store, and analyze healthcare data from various sources. HDS provides standardized data models and transformation tools to help create a multi-modal healthcare data warehouse, supporting industry standards like FHIR and DICOM, and ensuring compliance with regulations such as HIPAA and GDPR. HDS also has a growing list AI capabilities to generate and manage AI artifacts, like support for [Dragon Ambient eXperience (DAX) Copilot](https://learn.microsoft.com/en-us/industry/healthcare/dax-copilot-integration/overview?toc=%2Findustry%2Fhealthcare%2Ftoc.json&bc=%2Findustry%2Fbreadcrumb%2Ftoc.json), making it ideal to serve as the data layer for Agentic systems.

Below shows a sample data flow and use cases that HDS unlocks, going from raw FHIR ingestion to dynamic PowerBI reports.
![alt text](fabric_hds_pipeline.png)

### Prerequisites

The assumption is that you have already deployed Healthcare Agent Orchestrator (HAO) using the default blob storage. Additionally, it is expected you have already onboarded to Fabric and have a baseline understanding of its features and terminiology. More information can be found [here]().

## Deploy healthcare data solutions (HDS) to a Fabric Workspace

In a Fabric workspace, you will want to [deploy the clinical foundations capability](https://learn.microsoft.com/en-us/industry/healthcare/healthcare-data-solutions/healthcare-data-foundations-configure?toc=%2Findustry%2Fhealthcare%2Ftoc.json&bc=%2Findustry%2Fbreadcrumb%2Ftoc.json), which emulates a medallion architecture to transform raw NDJSON files into relational FHIR. 

![](./healthcare-data-foundations-artifacts.png)

> Note: You do ___NOT___ need to deploy sample data that is shipped with HDS. The next step will show you how to generate and ingest sample data.

## Generate Sample Data

The default storage solution for Healthcare Agent Orchestrator (HAO) uses blob storage. During deployment, the contents of the `infra/data` are uploaded to a storage account. We can re-use the same sample data but it needs to be properly formatted. There is a script `scripts/generate_fhir_resources.py` that needs to be executed to generate FHIR NDJSON files suitable for ingestion by HDS.

Run the script with the following argument to generate the corresponding files:
```
python generate_fhir_resources.py --fabric
```
The newly generated files will be located at `output/fabric_resources`


### Ingesting Sample Data

After generating the sample NDJSON files, you will need to upload them to the Bronze Lakehouse (healthcare1_msft_bronze) that was created during the capability deployment. Open the Lakehouse and expand the 'Files' folder in the left side panel. 

![](upload_sample_data.png)

### Run the ingestion pipeline

After uploading the data you want ingested, we need to run the clinical data ingestion pipeline. Navigate to the `healthcare1_msft_clinical_data_foundations_ingestion` data pipeline in your workspace. It should look like the screenshot below. Click on the 'Run' button, the pipeline should take about 10 minutes to complete. You can verify data was processed correctly by checking the notes table in the `healthcare1_msft_silver` lakehouse.

> NOTE: You can confirm data was ingested properly by opening the silver lakehouse and selecting the `DocumentReference` table which should now have some entries. If the pipeline completed successfully and you are not seeing any data being populated in the UI, try executing a query in the SQL Analytics Endpoint UI, there can be some latency before the data shows up properly. 

![](run_pipeline.png)

### Create a User Data Function (UDF)

We will create a User Data Function to expose the data in our Silver Lakehouse that realized relational FHIR. An overview of how to create a UDF can be found [here](https://learn.microsoft.com/en-us/fabric/data-engineering/user-data-functions/user-data-functions-overview).

1. Create the UDF in your workspace that has HDS deployed. When the editor page appears, add the sample code located at ```docs/fabric/udf.py```.

2. You will need to add a connection to your FHIR Lakehouse by selecting 'Manage Connections' and 'add data connection' in the 'Connections' tab in the side panel that opens. The connections in the sample code use the name "FHIR". It is important the make sure the alias your define matches the alias used in the function definition (see below).

3. Publish your UDF and test some of the endpoints with sample data. Publishing can take a few minutes.

![](udf_data_connection.png)

After creating the UDF, make note of the UDF id which will be used in the deployment. This id can be found in the url when opening the UDF. The pattern for the url is as follows:

```
https://powerbi.com/groups/<workspace_id>/userdatafunctions/<udf_id>?experience=power-bi
```

For example, the id in the url below would be `7691d553-f369-4de3-8ce1-58525c795123`
```
https://msit.powerbi.com/groups/73eb06f4-6494-4d6d-ab7e-f92faa5e8643/userdatafunctions/7691d553-f369-4de3-8ce1-58525c795123?experience=power-bi
```

### Onboarding to Fabric REST APIs

The Healthcare Agent Orchestrator (HAO) will interface with Microsoft Fabric by calling some of its [Public REST APIs](https://learn.microsoft.com/en-us/rest/api/fabric/articles/identity-support). In this example we will be using the APIs for Fabric's [User Data Functions](https://blog.fabric.microsoft.com/en-US/blog/service-principal-and-private-library-support-for-fabric-user-data-functions/).

If you are interested in exposing data using a Fabric GraphQL instance, more information can be found [here](https://learn.microsoft.com/en-us/fabric/data-engineering/connect-apps-api-graphql).

We can use Managed Identities that are already created as part of the HAO deployment for authentication when calling [Fabric REST APIs](https://learn.microsoft.com/en-us/rest/api/fabric/articles/using-fabric-apis)

### Creating a Security group

The service principal created by the default deployment doesn't have access to any of your Power BI content and APIs. To give the service principal access, we can create a security group in Microsoft Entra ID and then add the service principal you created to that security group. You can do this [manually](https://learn.microsoft.com/en-us/entra/fundamentals/how-to-manage-groups#create-a-basic-group-and-add-members) or by executing the script below.

```ps
# Sign in as an admin.
Connect-MgGraph -Scopes "Application.ReadWrite.All"

# Get the service principal that you created earlier.
$servicePrincipal = Get-MgServicePrincipal -Filter "AppId eq '<app-client-ID>'"

# Create an Azure AD security group.
$group = New-MgGroup -DisplayName "securitygroup1" -SecurityEnabled -MailEnabled:$False -MailNickName "notSet"
Write-Host "Object ID of new security group: " $($group.Id)

# Add the service principal to the group.
New-MgGroupMember -GroupId $($group.Id) -DirectoryObjectId $($servicePrincipal.Id)
```

### Configure Fabric Tenant Settings

On the Fabric side, you need to configure your Tenant settings in the [Admin Center](https://learn.microsoft.com/en-us/fabric/admin/admin-center) to allow the service principal to use the Fabric APIs.


![](admin-portal-option-settings-menu.png)

Make sure you have the setting enabled to allow service principals to use Fabric APIs and specify the security group created in the previous step.

![](admin-portal-allow-apis.png)

### Assign a Managed Identity to your Workspace

You can add the 'Orchestrator' identity to your Fabric Workspace by going to the Workspace landing page and selecting 'Manage Access' to show a side panel. From there, you can click 'Add people or groups' and enter the id or client id of your Orchestrator. **Make sure that the service principal is assigned an Admin role**.

![](managed_identity.png)


## Redploy the solution

There are two small changes that need to be made before redeploying:

```
azd env set CLINICAL_NOTES_SOURCE fabric
```

```
azd env set FABRIC_USER_DATA_FUNCTION_ENDPOINT <endpoint>
```

