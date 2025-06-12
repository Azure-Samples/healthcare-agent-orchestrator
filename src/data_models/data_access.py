# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import datetime
import logging
import os
from dataclasses import dataclass

from azure.core.credentials_async import AsyncTokenCredential
from azure.storage.blob import BlobSasPermissions, UserDelegationKey, generate_blob_sas
from azure.storage.blob.aio import BlobServiceClient

from data_models.chat_artifact_accessor import ChatArtifactAccessor
from data_models.chat_context_accessor import ChatContextAccessor
from data_models.clinical_note_accessor import ClinicalNoteAccessor
from data_models.fabric.fabric_clinical_note_accessor import FabricClinicalNoteAccessor
from data_models.fhir.fhir_clinical_note_accessor import FhirClinicalNoteAccessor
from data_models.image_accessor import ImageAccessor

logger = logging.getLogger(__name__)

class UserDelegationKeyDelegate:
    def __init__(self, blob_service_client: BlobServiceClient):
        self.blob_service_client = blob_service_client
        self.user_delegation_key = None

    async def get_user_delegation_key(self) -> UserDelegationKey:
        if self.is_expired():
            now_utc = datetime.datetime.now(datetime.UTC)
            key_start_time = now_utc - datetime.timedelta(minutes=3)
            key_expiry_time = key_start_time + datetime.timedelta(hours=1)

            self.user_delegation_key = await self.blob_service_client.get_user_delegation_key(
                key_start_time=key_start_time,
                key_expiry_time=key_expiry_time
            )

        return self.user_delegation_key

    def is_expired(self) -> bool:
        if self.user_delegation_key is None:
            return True
        expiry_utc = datetime.datetime.strptime(self.user_delegation_key.signed_expiry, "%Y-%m-%dT%H:%M:%SZ")
        now_utc = datetime.datetime.now(datetime.UTC)
        return now_utc.timestamp() >= expiry_utc.timestamp()


class BlobSasDelegate(UserDelegationKeyDelegate):
    def __init__(self, blob_service_client: BlobServiceClient):
        super().__init__(blob_service_client)

    async def get_blob_sas_url(
        self,
        url: str,
        permission: BlobSasPermissions = BlobSasPermissions(read=True),
        expiry_delta: datetime.timedelta = datetime.timedelta(hours=0.5),
    ) -> str:
        if "?" in url:
            raise ValueError("URL already contains a query string.")

        # Assumed URL format: https://<account_name>.blob.core.windows.net/<container_name>/<blob_name>
        container_name = url.split('/')[3]
        user_delegation_key = await self.get_user_delegation_key()
        account_name = self.blob_service_client.account_name
        blob_name = url[len(f"https://{account_name}.blob.core.windows.net/{container_name}/"):]
        expiry_time = datetime.datetime.now(datetime.UTC) + expiry_delta
        logger.info(f"url: {url}, blob_name: {blob_name}")

        # Generate the SAS token using the user delegation key
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=container_name,
            blob_name=blob_name,
            user_delegation_key=user_delegation_key,
            permission=permission,
            expiry=expiry_time
        )

        return f"{url}?{sas_token}"


@dataclass(frozen=True)
class DataAccess:
    """ Data access layer for the application. """
    blob_sas_delegate: BlobSasDelegate
    chat_artifact_accessor: ChatArtifactAccessor
    chat_context_accessor: ChatContextAccessor
    clinical_note_accessor: ClinicalNoteAccessor
    image_accessor: ImageAccessor


def create_data_access(
    blob_service_client: BlobServiceClient,
    credential: AsyncTokenCredential
) -> DataAccess:
    """ Factory function to create a DataAccess object. """
    # Create clinical note accessor based on the source
    clinical_notes_source = os.getenv("CLINICAL_NOTES_SOURCE")
    if clinical_notes_source == "fhir":
        # Note: You can change FhirClinicalNoteAccessor instantiation to use different authentication methods
        clinical_note_accessor = FhirClinicalNoteAccessor.from_credential(
            fhir_url=os.getenv("FHIR_SERVICE_ENDPOINT"),
            credential=credential,
        )
    elif clinical_notes_source == "fabric":
        clinical_note_accessor = FabricClinicalNoteAccessor.from_credential(
            fabric_user_data_function_endpoint=os.getenv("FABRIC_USER_DATA_FUNCTION_ENDPOINT"),
            credential=credential,
        )
    else:
        clinical_note_accessor = ClinicalNoteAccessor(blob_service_client)

    return DataAccess(
        blob_sas_delegate=BlobSasDelegate(blob_service_client),
        chat_artifact_accessor=ChatArtifactAccessor(blob_service_client),
        chat_context_accessor=ChatContextAccessor(blob_service_client),
        clinical_note_accessor=clinical_note_accessor,
        image_accessor=ImageAccessor(blob_service_client),
    )
