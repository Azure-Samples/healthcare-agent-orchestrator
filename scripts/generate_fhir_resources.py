import base64
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import argparse

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

def write_ndjson_file(file_path, resources):
    """Write a list of resources to a file in NDJSON format."""
    with open(file_path, "w") as f:
        for resource in resources:
            f.write(json.dumps(resource) + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate FHIR resources as NDJSON or individual files.")
    parser.add_argument("--fabric", action="store_true", help="If set, generate NDJSON files (one file per resource type, one JSON per line).")
    args = parser.parse_args()

    output_type_dir = "fabric_resources" if args.fabric else "fhir_resources"
    output_dir = os.path.join("output", output_type_dir)
    patient_input_dir = os.path.join(os.getcwd(), "infra", "patient_data")
    patient_output_dir = os.path.join(os.getcwd(), output_dir)
    document_reference_output_dir = os.path.join(os.getcwd(), output_dir)

    patient_data_items = os.listdir(patient_input_dir)

    all_patients = []
    all_document_references = []

    for patient_folder in patient_data_items:
        folder_path = os.path.join(patient_input_dir, patient_folder)
        if os.path.isdir(folder_path):
            patient_resource = create_patient_resource(patient_folder)
            patient_resource = add_last_updated_to_patient(patient_resource)
            fhir_patient_id = patient_resource["id"]

            if args.fabric:
                all_patients.append(patient_resource)
            else:
                patient_file_name = os.path.join("patients", f"{patient_folder}.json")
                patient_file_path = os.path.join(patient_output_dir, patient_file_name)
                os.makedirs(os.path.dirname(patient_file_path), exist_ok=True)
                with open(patient_file_path, "w") as patient_file:
                    patient_file.write(json.dumps(patient_resource) + "\n")

            clinical_notes_dir = os.path.join(patient_input_dir, patient_folder, "clinical_notes")
            if os.path.exists(clinical_notes_dir):
                clinical_notes = os.listdir(clinical_notes_dir)
                for clinical_note in clinical_notes:
                    clinical_note_file = os.path.join(clinical_notes_dir, clinical_note)
                    with open(clinical_note_file, "r") as f:
                        note = f.read()
                        note_json = json.loads(note)
                        note_id = os.path.basename(clinical_note_file).split(".")[0]
                        document_reference_resource = create_document_reference(
                            fhir_patient_id, note_id, json.dumps(note_json))
                        document_reference_resource = add_last_updated_to_document_reference(document_reference_resource)
                        if args.fabric:
                            all_document_references.append(document_reference_resource)
                        else:
                            document_reference_file_name = os.path.join("document_references", clinical_note)
                            document_reference_file_path = os.path.join(document_reference_output_dir, document_reference_file_name)
                            os.makedirs(os.path.dirname(document_reference_file_path), exist_ok=True)
                            with open(document_reference_file_path, "w") as document_reference_file:
                                document_reference_file.write(json.dumps(document_reference_resource) + "\n")

    # If --fabric, write NDJSON files
    if args.fabric:
        os.makedirs(patient_output_dir, exist_ok=True)
        os.makedirs(document_reference_output_dir, exist_ok=True)
        
        # Write all patients to one NDJSON file
        patients_ndjson_path = os.path.join(patient_output_dir, "Patient.ndjson")
        write_ndjson_file(patients_ndjson_path, all_patients)
        
        # Write all document references to one NDJSON file
        docref_ndjson_path = os.path.join(document_reference_output_dir, "DocumentReference.ndjson")
        write_ndjson_file(docref_ndjson_path, all_document_references)
