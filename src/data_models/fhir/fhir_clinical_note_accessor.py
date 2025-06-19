# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import asyncio
import base64
import json
import logging
from typing import Any, Callable, Coroutine, Dict, List

import aiohttp
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import get_bearer_token_provider
import urllib

logger = logging.getLogger(__name__)


class FhirClinicalNoteAccessor:

    @staticmethod
    def from_credential(fhir_url: str, credential: AsyncTokenCredential) -> 'FhirClinicalNoteAccessor':
        """ Creates an instance of FhirClinicalNoteAccessor using Azure credential."""
        token_provider = get_bearer_token_provider(credential, f"{fhir_url}/.default")
        return FhirClinicalNoteAccessor(fhir_url, token_provider)

    @staticmethod
    def from_client_secret(tenant_id: str, client_id: str, client_secret: str, fhir_url: str) -> 'FhirClinicalNoteAccessor':
        """ Creates an instance of FhirClinicalNoteAccessor using client secret."""
        async def bearer_token_provider() -> str:
            token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/token"
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            data = {
                "grant_type": "client_credentials",
                "resource": fhir_url,
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": f"{fhir_url}/.default"
            }
            async with aiohttp.request('POST', token_url, data=data, headers=headers) as resp:
                resp.raise_for_status()
                json_response = await resp.json()
                return json_response["access_token"]

        return FhirClinicalNoteAccessor(fhir_url, bearer_token_provider)

    def __init__(self, fhir_url: str, bearer_token_provider: Callable[[], Coroutine[Any, Any, str]]):
        """
        Initializes the FhirClinicalNoteAccessor.

        :param fhir_url: The base URL of the FHIR server.
        :param credential: The Azure credential for authentication.
        """
        if not fhir_url:
            raise ValueError("FHIR URL is required.")
        if not bearer_token_provider:
            raise ValueError("bearer_token_provider is required.")

        self.fhir_url = fhir_url
        self.bearer_token_provider = bearer_token_provider

    async def get_headers(self) -> dict:
        """
        Returns the headers required for FHIR API requests.

        :return: A dictionary of headers.
        """
        return {
            "Authorization": f"Bearer {await self.bearer_token_provider()}",
            "Content-Type": "application/json",
        }
    
    @staticmethod
    def get_continuation_token(links):
        for link in links:
            if "relation" in link and link["relation"] == "next":
                return link["url"].split("?", 1)[-1]
        return None

    async def fetch_all_entries(
        self,
        base_url: str,
        result_count_limit: int = 100,
        extract_entries=lambda r: r.get("entry", []),
        extract_continuation_token=lambda r: FhirClinicalNoteAccessor.get_continuation_token(r.get("link", []))
    ) -> List[dict]:
        """
        Generic function to fetch all entries from a paginated FHIR resource endpoint.
        :param base_url: The initial FHIR resource URL (e.g., f"{fhir_url}/Patient").
        :param result_count_limit: Maximum number of entries to fetch.
        :param extract_entries: Function to extract entries from the response JSON.
        :param extract_continuation_token: Function to extract continuation token from the response JSON.
        :return: List of resource entries.
        """
        entries = []
        url = base_url
        parsed_url = urllib.parse.urlparse(url)
        async with aiohttp.ClientSession() as session:
            while url and len(entries) < result_count_limit:
                logger.debug(f"Fetching from URL: {url}")
                async with session.get(url, headers=await self.get_headers()) as response:
                    response.raise_for_status()
                    response_json = await response.json()
            
                new_entries = extract_entries(response_json)
                entries.extend(new_entries)
                if len(entries) >= result_count_limit:
                    break
                token = extract_continuation_token(response_json)
                if token:
                    # Append or replace query string with continuation token
                    url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}?{token}"
                else:
                    url = None
        return entries[:result_count_limit]

    async def get_patients(self) -> List[str]:
        """
        Retrieves a list of patient IDs from the FHIR server.

        :return: A list of patient IDs.
        """
        entries = await self.fetch_all_entries(
            base_url=f"{self.fhir_url}/Patient",
            result_count_limit=100
        )
        return [entry["resource"]['name'][0]['given'][0] for entry in entries]

    async def get_patient_id_map(self) -> List[str]:
        """
        Retrieves a list of patient IDs from the FHIR server.

        :return: A list of patient IDs.
        """
        entries = await self.fetch_all_entries(
            base_url=f"{self.fhir_url}/Patient",
            result_count_limit=100
        )

        return {entry["resource"]['name'][0]['given'][0]: entry["resource"]['id'] for entry in entries}

    async def get_metadata_list(self, patient_id: str) -> List[Dict[str, str]]:
        """
        Retrieves metadata for clinical notes associated with a given patient ID.
        :param patient_id: The ID of the patient.
        :return: A list of metadata dictionaries for clinical notes.
        """
        patient_id_map = await self.get_patient_id_map()
        if patient_id in patient_id_map:
            patient_id = patient_id_map[patient_id]
        
        document_references = await self.fetch_all_entries(
            base_url=f"{self.fhir_url}/DocumentReference?subject=Patient/{patient_id}&_elements=subject,id",
            result_count_limit=100
        )
        entries = []
        for document_reference in document_references:
            if "resource" not in document_reference:
                continue
            if "subject" not in document_reference["resource"]:
                continue
            if "reference" not in document_reference["resource"]["subject"]:
                continue
            if patient_id not in document_reference["resource"]["subject"]["reference"]:
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
        headers = await self.get_headers()
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                document_reference = await response.json()
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
