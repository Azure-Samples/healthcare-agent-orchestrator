import json
import logging
from datetime import datetime, timezone
from time import time
from typing import Dict, Optional, Tuple

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob.aio import BlobServiceClient

logger = logging.getLogger(__name__)


class PatientContextRegistryAccessor:
    """
    Manages patient context registry JSON files in blob storage.
    Tracks which patients have been encountered in each conversation session.
    """

    def __init__(self, blob_service_client: BlobServiceClient, container_name: str = "chat-sessions"):
        self.blob_service_client = blob_service_client
        self.container_client = blob_service_client.get_container_client(container_name)

    def get_registry_blob_path(self, conversation_id: str) -> str:
        """Get blob path for patient context registry file."""
        return f"{conversation_id}/patient_context_registry.json"

    async def _write_json_to_blob(self, blob_path: str, data: dict) -> None:
        """Write JSON data to blob storage."""
        json_str = json.dumps(data, indent=2)
        blob_client = self.container_client.get_blob_client(blob_path)
        await blob_client.upload_blob(json_str, overwrite=True)

    async def read_registry(self, conversation_id: str) -> Tuple[Dict[str, Dict], Optional[str]]:
        """Read patient context registry. Returns (patient_registry, active_patient_id)."""
        start = time()
        try:
            blob_path = self.get_registry_blob_path(conversation_id)
            blob_client = self.container_client.get_blob_client(blob_path)
            blob = await blob_client.download_blob()
            blob_str = await blob.readall()
            decoded_str = blob_str.decode("utf-8")
            registry_data = json.loads(decoded_str)

            logger.info(f"Read patient context registry for {conversation_id}. Duration: {time() - start}s")
            return registry_data.get("patient_registry", {}), registry_data.get("active_patient_id")

        except ResourceNotFoundError:
            logger.info(f"No existing patient context registry for {conversation_id}")
            return {}, None
        except Exception as e:
            logger.warning(f"Failed to read patient context registry for {conversation_id}: {e}")
            return {}, None

    async def write_registry(self, conversation_id: str, patient_registry: Dict[str, Dict], active_patient_id: str = None):
        """Write patient context registry to blob storage."""
        try:
            registry_data = {
                "conversation_id": conversation_id,
                "active_patient_id": active_patient_id,
                "patient_registry": patient_registry,
                "last_updated": datetime.utcnow().isoformat()
            }

            blob_path = self.get_registry_blob_path(conversation_id)
            await self._write_json_to_blob(blob_path, registry_data)
            logger.info(f"Wrote patient registry for conversation {conversation_id}")

        except Exception as e:
            logger.error(f"Failed to write patient registry: {e}")
            raise

    async def update_patient_registry(self, conversation_id: str, patient_id: str, registry_entry: Dict, active_patient_id: str = None) -> None:
        """Update registry entry for a specific patient in the conversation."""
        current_registry, current_active = await self.read_registry(conversation_id)
        current_registry[patient_id] = {
            **registry_entry,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        # Use provided active_patient_id or keep current
        final_active = active_patient_id if active_patient_id is not None else current_active
        await self.write_registry(conversation_id, current_registry, final_active)

    async def archive_registry(self, conversation_id: str) -> None:
        """Archive patient context registry before clearing."""
        start = time()
        try:
            # Read current registry
            current_registry, active_patient_id = await self.read_registry(conversation_id)
            if not current_registry:
                logger.info("No patient context registry to archive for %s", conversation_id)
                return

            # Create archive
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            archive_blob_path = "%s/%s_patient_context_registry_archived.json" % (conversation_id, timestamp)

            archive_data = {
                "conversation_id": conversation_id,
                "archived_at": datetime.now(timezone.utc).isoformat(),
                "active_patient_id": active_patient_id,
                "patient_registry": current_registry
            }

            await self._write_json_to_blob(archive_blob_path, archive_data)

            # Clear current registry by deleting the blob
            try:
                blob_path = self.get_registry_blob_path(conversation_id)
                await self.container_client.delete_blob(blob_path)
                logger.info("Cleared patient context registry for %s", conversation_id)
            except ResourceNotFoundError:
                logger.info("No patient context registry to clear for %s", conversation_id)

            logger.info("Archived patient context registry for %s. Duration: %ss", conversation_id, time() - start)
        except Exception as e:
            logger.error("Failed to archive patient context registry for %s: %s", conversation_id, e)
            raise
