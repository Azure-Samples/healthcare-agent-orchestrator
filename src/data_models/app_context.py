# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import get_bearer_token_provider
from azure.storage.blob.aio import BlobServiceClient

from data_models.data_access import DataAccess


@dataclass(frozen=True)
class AppContext:
    """ Application context for commonly used objects in the application. """
    all_agent_configs: list[dict]
    blob_service_client: BlobServiceClient
    credential: AsyncTokenCredential
    data_access: DataAccess

    @property
    def azureml_token_provider(self) -> Callable[[], Coroutine[Any, Any, str]]:
        return get_bearer_token_provider(self.credential, "https://ml.azure.com/.default")

    @property
    def cognitive_services_token_provider(self) -> Callable[[], Coroutine[Any, Any, str]]:
        return get_bearer_token_provider(self.credential, "https://cognitiveservices.azure.com/.default")
