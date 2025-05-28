import base64
import json
import os
from uuid import uuid4
from datetime import datetime, timedelta, timezone

def create_patient_resource(patient_folder: str):
    return {
        "resourceType": "Patient",
        "id": str(uuid4()),
        "name": [
            {
                "given": [patient_folder, "LastName"],
                "family": "Doe",
            }
        ],
        "gender": "female",
        "birthDate": "1967-05-05"
    }

def create_document_reference(fhir_patient_id, note_id: str, note_content: str):
    note_content = base64.b64encode(note_content.encode('utf-8')).decode('utf-8')
    return {
        "content": [
            {
                "attachment": {
                    "contentType": "text/plain; charset=utf-8",
                    "data": note_content
                },
                "format": {
                    "code": "urn:ihe:iti:xds:2017:mimeTypeSufficient",
                    "display": "mimeType Sufficient",
                    "system": "http://ihe.net/fhir/ValueSet/IHE.FormatCode.codesystem"
                }
            }
        ],
        "date": create_last_updated_formatted_date(),
        "id": note_id,
        "identifier": [],
        "resourceType": "DocumentReference",
        "status": "current",
        "subject": {
            "reference": f"Patient/{fhir_patient_id}"
        },
    }

def add_last_updated_to_document_reference(document_reference):
    if "meta" not in document_reference:
        document_reference["meta"] = {}
    document_reference["meta"]["lastUpdated"] = create_last_updated_formatted_date()
    return document_reference

def add_last_updated_to_patient(patient):
    if "meta" not in patient:
        patient["meta"] = {}
    patient["meta"]["lastUpdated"] = create_last_updated_formatted_date()
    return patient

def create_last_updated_formatted_date():
    """
    Returns yesterday's date in the format: YYYY-MM-DDTHH:MM:SS.sss+00:00
    """
    dt = datetime.now(timezone.utc) - timedelta(days=1)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"

if __name__ == "__main__":

    root = "infra/patient_data"
    target = "ahds"
    intermediate_folder = "ahds"
    patient_output_dir = f"infra/fhir_resources/{intermediate_folder}"
    document_reference_output_dir = f"infra/fhir_resources/{intermediate_folder}/"
    patient_folders = os.listdir(root)

    for patient_folder in patient_folders:
        folder_path = os.path.join(os.getcwd(), root, patient_folder)
        if os.path.isdir(folder_path):

            patient_resource = create_patient_resource(patient_folder)
            patient_file_name = f"patients/{patient_folder}.json"
            patient_file_path = os.path.join(os.getcwd(), patient_output_dir, patient_file_name)
            
            if os.path.exists(os.path.dirname(patient_file_path)) == False:
                os.makedirs(os.path.dirname(patient_file_path))
            
            with open(patient_file_path, "a") as patient_file:
                patient_file.write(json.dumps(patient_resource) + "\n")
            
            fhir_patient_id = patient_resource["id"]
            clinical_notes = os.listdir(os.path.join(root, patient_folder, "clinical_notes"))
            
            for clinical_note in clinical_notes:
                clinical_note_file = os.path.join(root, patient_folder, "clinical_notes", clinical_note)
                
                with open(clinical_note_file, "r") as f:
                    document_reference_file_name = f"document_references/{clinical_note}"
                    document_reference_file_path = os.path.join(os.getcwd(), document_reference_output_dir, document_reference_file_name)
                    
                    if os.path.exists(os.path.dirname(document_reference_file_path)) == False:
                        os.makedirs(os.path.dirname(document_reference_file_path))
                    
                    with open(document_reference_file_path, "a") as document_reference_file:
                        note = f.read()
                        note_json = json.loads(note)
                        note_id = os.path.basename(clinical_note_file).split(".")[0]
                        document_reference_resource = create_document_reference(
                            fhir_patient_id, note_id, json.dumps(note_json))
                        document_reference_file.write(json.dumps(document_reference_resource) + "\n")