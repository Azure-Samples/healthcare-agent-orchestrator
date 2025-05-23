# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import os

import aiohttp
from semantic_kernel.functions import kernel_function

from data_models.plugin_configuration import PluginConfiguration


def create_plugin(plugin_config: PluginConfiguration):
    return CxrReportGenPlugin(plugin_config)


class CxrReportGenPlugin:
    def __init__(self, config: PluginConfiguration):
        self.azureml_token_provider = config.azureml_token_provider
        self.data_access = config.data_access
        self.url = config.agent_config["hls_model_endpoint"].get("cxr_report_gen")
        self.root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @kernel_function()
    async def generate_findings(self, patient_id: str, filename: str, indication: str):
        """
        Generates findings for a given patient based on the provided image (chest x-ray only) and indication. Indication should be short, e.g. "Chest pain" or "Pneumonia". 

        Args:
            patient_id (str): The ID of the patient.
            filename (str): The name of the chest x-ray file.
            indication (str): The medical indication or reason for the imaging.

        Returns:
            dict: The JSON response from the server containing the generated findings.
        """
        image_stream = await self.data_access.image_accessor.read(patient_id, filename)
        base64_image = base64.b64encode(image_stream.read()).decode("utf-8")
        body = {
            "input_data": {
                "data": [[base64_image, indication]],
                "columns": ["frontal_image", "indication"],
                "index": [0],
            }
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {await self.azureml_token_provider()}",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(self.url, json=body, headers=headers) as resp:
                resp.raise_for_status()
                return await resp.json()
