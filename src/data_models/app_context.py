# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from dataclasses import dataclass

from azure.identity import ManagedIdentityCredential
from azure.storage.blob.aio import BlobServiceClient

from data_models.data_access import DataAccess


@dataclass(frozen=True)
class AppContext:
    all_agent_configs: list[dict]
    blob_service_client: BlobServiceClient
    credential: ManagedIdentityCredential
    data_access: DataAccess
