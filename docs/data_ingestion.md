# Data Ingestion

This code sample uses Azure Blob Storage to store patient data used by agents. Patient data contains clinical notes and images. Clinical notes are stored in JSON. Images are stored in PNG.

> [!CAUTION]
> The Healthcare Agent Orchestration framework is not meant for processing identifiable health records. Ensure that you follow all PHI/PII regulations when configuring or using the system.

## Add Your Own Data

> [!WARNING]
> Data will be publicly available unless you configure authentication as mentioned in [Infrastructure](./infra.md#security)

To manage patient data, follow these steps:

1. **Create a New Folder**: 
    - Navigate to `infra/patient_data`.
    - Create a new folder named after the patient.
    - Create a `clinical_notes` subfolder.
    - Create an `images` subfolder.

2. **Add Clinical Notes**:
    - Inside the `clinical_notes` subfolder, create JSON files for each clinical note entry.
    - Each clinical note must contain the following attributes:
        - id: a unique identifier of the clinical note
        - date: the date of the clinical note
        - type: the type of clinical note (e.g. "progress note", "telephone encounter", "pathology", etc...)
        - text: the clinical note text

3. **Add Images**:
    - Inside the `images` subfolder, copy patient image files to the folder.
    - Only PNG images are supported.
    - Create a `metadata.json` file to describe the images.
    - `metadata.json` is a list of JSON objects that contain the following attributes:
        - filename: the name of an image file
        - type: a string that describes the image file (e.g. "CT image", "pathology image", "x-ray image", etc...)

4. **Upload Patient Data**:
    - From the command line, run `scripts/uploadPatientData.ps1` for Windows or `scripts/uploadPatientData.sh` for Linux/Mac to upload patient data to storage.
    - Alternatively, running `azd up` or `azd provision` will also upload patient data to Azure Blob Storage. `scripts/uploadPatientData.ps1` and `scripts/uploadPatientData.sh` are called in the `postprovision` step of [azure.yaml](../azure.yaml).

5. **Test New Patient Data**:

    From a Teams chat, ask an agent to perform a task using the new patient ID. If you would like to create a personal chat for testing, see [Create Personal Teams Chat](./teams.md#create_personal_chat).

    - For new clinical notes and images, use the **Orchestrator** agent.
        - Send the message "@Orchestrator prepare tumor board for patient id *new_patient_id*". Proceed with the plan proposed by the **Orchestrator** agent.
        - Verify the patient timeline is created using the new clinical notes.
        - Click the source links to verify that the new clinical notes are loaded correctly (id, date, type, and text).
        - Verify new images are loaded by the **Radiology** agent.
    - For new clinical notes only, use the **PatientHistory** agent.
        - Send the message "@PatientHistory create patient timeline for patient id *new_patient_id*".
        - Verify the patient timeline is created using the new clinical notes.
        - Click the source links to verify that the new clinical notes are loaded correctly (id, date, type, and text).



