# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import os

import aiohttp
import numpy as np
import scipy.special
from semantic_kernel.functions import kernel_function

from data_models.plugin_configuration import PluginConfiguration


def create_plugin(plugin_config: PluginConfiguration):
    return MedImageInsightPlugin(plugin_config)


class MedImageInsightPlugin:
    def __init__(self, config: PluginConfiguration):
        self.azureml_token_provider = config.azureml_token_provider
        self.data_access = config.data_access
        self.url = config.agent_config["hls_model_endpoint"].get("med_image_insight")
        self.root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @kernel_function(description="Calculates the likelihood that a tumor is malignant")
    async def tumor_malignant(self, patient_id: str, filename: str, prompt: str):
        image_stream = await self.data_access.image_accessor.read(patient_id, filename)
        base64_image = base64.b64encode(image_stream.read()).decode("utf-8")
        body = {
            "input_data": {
                "data": [
                    [base64_image, "histopathology, H&E stain, lung, malignant"],
                    [base64_image, "histopathology, H&E stain, lung, non-malignant"],
                ],
                "columns": ["image", "text"],
                "index": [0, 1],
            }
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {await self.azureml_token_provider()}",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(self.url, json=body, headers=headers) as resp:
                resp.raise_for_status()
                result = await resp.json()

        sf = result[0]["scaling_factor"]
        tf0 = result[0]["text_features"]
        tf1 = result[1]["text_features"]

        if0 = result[0]["image_features"][0]
        if1 = result[1]["image_features"][0]

        iv = np.array(if0)
        tv0 = np.array(tf0)
        tv1 = np.array(tf1)
        scores = scipy.special.softmax(
            np.array([np.dot(iv, tv0) * sf, np.dot(iv, tv1) * sf])
        )

        return {
            "malignant": scores[0],
            "non-malignant": scores[1],
        }
