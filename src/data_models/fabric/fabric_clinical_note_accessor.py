# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import asyncio
import logging
from typing import Any, Callable, Coroutine, List, Optional, Tuple
import json
import base64
from datetime import date, timedelta

import re
import aiohttp
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import get_bearer_token_provider

logger = logging.getLogger(__name__)

class FabricClinicalNoteAccessor:
    def __init__(
        self,
        fabric_user_data_function_endpoint: str,
        bearer_token_provider: Callable[[], Coroutine[Any, Any, str]],
    ):
        self.fabric_user_data_function_endpoint = fabric_user_data_function_endpoint
        workspace_id, data_function_id = self.__parse_fabric_endpoint(fabric_user_data_function_endpoint)
        self.api_endpoint = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/userDataFunctions/{data_function_id}"
        self.bearer_token_provider = bearer_token_provider

    def __parse_fabric_endpoint(self, url: str) -> Optional[Tuple[str, str]]:
        """
        Parses a Fabric API URL to extract the workspace_id and data_function_id.

        Supports both the following patterns:
        https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/userDataFunctions/{data_function_id}
        and
        https://msit.powerbi.com/groups/{workspace_id}/userdatafunctions/{data_function_id}

        :param url: The Fabric API URL.
        :return: Tuple of (workspace_id, data_function_id) if found, else None.
        """
        # Try both possible patterns (case-insensitive for 'userdatafunctions')
        patterns = [
            r"/workspaces/([^/]+)/userDataFunctions/([^/]+)",
            r"/groups/([^/]+)/userdatafunctions/([^/]+)"
        ]
        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                workspace_id, data_function_id = match.groups()
                return workspace_id, data_function_id
        return None

    @staticmethod
    def from_credential(fabric_user_data_function_endpoint: str, credential: AsyncTokenCredential) -> 'FabricClinicalNoteAccessor':
        """ Creates an instance of FabricClinicalNoteAccessor using Azure credential."""
        token_provider = get_bearer_token_provider(credential, f"https://analysis.windows.net/powerbi/api")
        return FabricClinicalNoteAccessor(fabric_user_data_function_endpoint, token_provider)

    async def get_headers(self) -> dict:
        """
        Returns the headers required for Fabric API requests.

        :return: A dictionary of headers.
        """
        return {
            "Authorization": f"Bearer {await self.bearer_token_provider()}",
            "Content-Type": "application/json",
        }

    async def get_patients(self) -> list[str]:
        """Get the list of patients."""
        target_endpoint = f"{self.api_endpoint}/functions/get_patients_by_id/invoke"
        headers = await self.get_headers()
        async with aiohttp.ClientSession() as session:
            async with session.post(target_endpoint, json={}, headers=headers) as response:
                response.raise_for_status()
                content = await response.content.read()
                data = json.loads(content.decode('utf-8'))
        return data['output']['ids']

    async def get_metadata_list(self, patient_id: str) -> list[dict[str, str]]:
        """Get the clinical note URLs for a given patient ID."""
        target_endpoint = f"{self.api_endpoint}/functions/get_clinical_notes_by_patient_id/invoke"
        headers = await self.get_headers()
        async with aiohttp.ClientSession() as session:
            async with session.post(target_endpoint, json={"patientId": patient_id}, headers=headers) as response:
                response.raise_for_status()
                content = await response.content.read()
                data = json.loads(content.decode('utf-8'))
        document_reference_ids = data['output']

        return [
            {
                "id": doc_ref_id,
                "type": "clinical note",
            } for doc_ref_id in document_reference_ids
        ]

    async def read(self, patient_id: str, note_id: str) -> str:
        """Read the clinical note for a given patient ID and note ID."""
        target_endpoint = f"{self.api_endpoint}/functions/get_clinical_note_by_patient_id/invoke"
        headers = await self.get_headers()
        async with aiohttp.ClientSession() as session:
            async with session.post(target_endpoint, json={"noteId": note_id}, headers=headers) as response:
                response.raise_for_status()
                content = await response.content.read()
                data = json.loads(content.decode('utf-8'))
        document_reference = data["output"]
        document_reference_data = document_reference["content"][0]["attachment"]["data"]

        note_content = base64.b64decode(document_reference_data).decode("utf-8")

        note_json = {}
        try:
            note_json = json.loads(note_content)
            note_json['id'] = note_id
        except json.JSONDecodeError as e:

            # Try to handle note content that is not JSON
            if note_content:
                target_date = date.today() - timedelta(days=30)
                target_date.isoformat()
                note_json = {
                    "id": note_id,
                    "text": note_content,
                    "date": target_date.isoformat(),
                    "type": "clinical note",
                }

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