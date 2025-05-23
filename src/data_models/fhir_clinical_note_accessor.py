import asyncio
import base64
import json
from typing import Dict, List

import requests


class FhirClinicalNoteAccessor:
    def __init__(self, fhir_url: str, tenant_id: str, client_id: str, client_secret: str):
        """
        Initializes the FhirClinicalNoteAccessor.

        :param fhir_url: The base URL of the FHIR server.
        :param tenant_id: The Azure tenant ID.
        :param client_id: The Azure client ID.
        :param client_secret: The Azure client secret.
        """
        self.fhir_url = fhir_url
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret

    def get_access_token(self) -> str:
        """
        Retrieves an access token for authenticating with the FHIR server.

        :return: The access token.
        """
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "grant_type": "client_credentials",
            "resource": self.fhir_url,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": f"{self.fhir_url}/.default"
        }
        response = requests.post(token_url, headers=headers, data=data)
        response.raise_for_status()  # Raise an error for bad responses
        return response.json()["access_token"]

    def get_headers(self) -> dict:
        """
        Returns the headers required for FHIR API requests.

        :return: A dictionary of headers.
        """
        return {
            "Authorization": f"Bearer {self.get_access_token()}",
            "Content-Type": "application/json",
        }

    async def get_patients(self) -> List[str]:
        """
        Retrieves a list of patient IDs from the FHIR server.

        :return: A list of patient IDs.
        """
        url = f"{self.fhir_url}/Patient"
        response = requests.get(url, headers=self.get_headers())
        response.raise_for_status()
        patients = response.json().get("entry", [])
        return [entry["resource"]['name'][0]['given'][0] for entry in patients]

    async def get_patient_id_map(self) -> List[str]:
        """
        Retrieves a list of patient IDs from the FHIR server.

        :return: A list of patient IDs.
        """
        url = f"{self.fhir_url}/Patient"
        response = requests.get(url, headers=self.get_headers())
        response.raise_for_status()
        patients = response.json().get("entry", [])

        return {entry["resource"]['name'][0]['given'][0]: entry["resource"]['id'] for entry in patients}

    async def get_metadata_list(self, patient_id: str) -> List[Dict[str, str]]:
        """
        Retrieves metadata for clinical notes associated with a given patient ID.

        :param patient_id: The ID of the patient.
        :return: A list of metadata dictionaries for clinical notes.
        """
        patient_id_map = await self.get_patient_id_map()

        if patient_id in patient_id_map:
            patient_id = patient_id_map[patient_id]

        url = f"{self.fhir_url}/DocumentReference?subject=Patient/{patient_id}"
        response = requests.get(url, headers=self.get_headers())
        response.raise_for_status()
        document_references = response.json().get("entry", [])

        entries = []
        for document_reference in document_references:
            if "resource" not in document_reference:
                continue
            if "subject" not in document_reference["resource"]:
                continue
            if "reference" not in document_reference["resource"]["subject"]:
                continue

            print(document_reference["resource"]["subject"]["reference"])
            if patient_id not in document_reference["resource"]["subject"]["reference"]:
                print(document_reference["resource"]["subject"]["reference"])
                continue

            entries.append({
                "id": document_reference["resource"]["id"],
                "type": document_reference["resource"]["type"]["text"] if "type" in document_reference["resource"] else "clinical note",
            })

        return entries

    async def read(self, patient_id: str, note_id: str) -> str:
        """
        Retrieves the content of a clinical note for a given patient ID and note ID.

        :param patient_id: The ID of the patient.
        :param note_id: The ID of the clinical note.
        :return: The content of the clinical note.
        """
        url = f"{self.fhir_url}/DocumentReference/{note_id}"
        response = requests.get(url, headers=self.get_headers())
        response.raise_for_status()
        document_reference = response.json()
        note_content = document_reference["content"][0]["attachment"]["data"]

        note_json = json.loads(base64.b64decode(note_content).decode("utf-8"))

        note_json['id'] = note_id

        return json.dumps(note_json)

    async def read_all(self, patient_id: str) -> List[str]:
        """
        Retrieves all clinical notes for a given patient ID.

        :param patient_id: The ID of the patient.
        :return: A list of clinical note contents.
        """
        metadata_list = await self.get_metadata_list(patient_id)
        notes = []
        batch_size = 10
        for i in range(0, len(metadata_list), batch_size):
            batch_input = metadata_list[i:i + batch_size]
            batch = [self.read(patient_id, note["id"]) for note in batch_input]
            batch_results = await asyncio.gather(*batch)
            notes.extend(batch_results)
        return notes
