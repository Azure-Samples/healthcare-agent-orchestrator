# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import json
import logging
import os
from io import BytesIO

import aiohttp
import cv2
import matplotlib.pyplot as plt
import numpy as np
from semantic_kernel.functions import kernel_function

from data_models.chat_artifact import ChatArtifact, ChatArtifactIdentifier
from data_models.plugin_configuration import PluginConfiguration

logger = logging.getLogger(__name__)


def create_plugin(plugin_config: PluginConfiguration):
    return MedImageParsePlugin(plugin_config)


def decode_json_to_array(json_encoded):
    """Decode an image pixel data array in JSON.
    Return image pixel data as an array.
    """
    # Parse the JSON string
    array_metadata = json.loads(json_encoded)
    # Extract Base64 string, shape, and dtype
    base64_encoded = array_metadata["data"]
    shape = tuple(array_metadata["shape"])
    dtype = np.dtype(array_metadata["dtype"])
    # Decode Base64 to byte string
    array_bytes = base64.b64decode(base64_encoded)
    # Convert byte string back to NumPy array and reshape
    array = np.frombuffer(array_bytes, dtype=dtype).reshape(shape)
    return array


def find_longest_length(image_features, file_path):
    image = cv2.cvtColor(np.asarray(image_features[0, :, :]), cv2.COLOR_GRAY2BGR)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    thresh_img = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

    contours, hierarchy = cv2.findContours(
        thresh_img, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
    )
    max_contour = max(contours, key=cv2.contourArea)

    # Get the length of the longest axis of the maximum contour
    x_y, (width, height), angle = cv2.minAreaRect(max_contour)
    box = np.int64(cv2.boxPoints((x_y, (width, height), angle)))
    cv2.drawContours(image, [box], 0, (36, 255, 12), 3)

    max_length = max(width, height)
    return max_length


class MedImageParsePlugin:
    def __init__(self, config: PluginConfiguration):
        self.azureml_token_provider = config.azureml_token_provider
        self.data_access = config.data_access
        self.url = config.agent_config["hls_model_endpoint"].get("med_image_parse")
        self.root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @kernel_function(description="Calculates the tumor size")
    async def calculate_tumor_size(self, patient_id: str, filename: str, prompt: str):
        image_stream = await self.data_access.image_accessor.read(patient_id, filename)
        base64_image = base64.b64encode(image_stream.read()).decode("utf-8")
        body = {
            "input_data": {
                "data": [[base64_image, prompt]],
                "columns": ["image", "text"],
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
                result_list = await resp.json()

        image_features_str = result_list[0]["image_features"]
        image_features = decode_json_to_array(image_features_str)
        s1 = np.sum(image_features[0, :, :] > 128)

        # Save the segmentation masks to files
        await self.save_segmentation_masks(image_stream, filename, image_features)

        return {
            "volume": s1,
            "longest_length": find_longest_length(image_features, file_path=filename),
        }

    async def save_segmentation_masks(
        self, orig_image_stream: BytesIO, orig_image_filename: str, segmentation_masks: np.ndarray
    ) -> None:
        """ Save a list of segmentation mask over an image. """
        conversation_id = self.chat_ctx.conversation_id
        patient_id = self.chat_ctx.patient_id

        # Read the original image
        orig_image_stream.seek(0)
        orig_image = plt.imread(orig_image_stream)

        # Handle grayscale images
        is_color = len(orig_image.shape) == 3
        color_image = orig_image if is_color else np.stack((orig_image,) * 3, axis=2)

        self.chat_ctx.display_image_urls = []

        for i, mask in enumerate(segmentation_masks):
            # Overlay the mask on the original image
            mask_temp = color_image.copy()
            mask_temp[mask > 128] = [1, 0, 0, 0.9] if is_color else [1, 0, 0]

            # Save the mask to a file
            orig_image_prefix, orig_image_ext = os.path.splitext(orig_image_filename)
            artifact_id = ChatArtifactIdentifier(
                conversation_id=conversation_id,
                patient_id=patient_id,
                filename=f"{orig_image_prefix}-mask{i}{orig_image_ext}"
            )

            stream = BytesIO()
            plt.imsave(stream, mask_temp)

            artifact = ChatArtifact(artifact_id=artifact_id, data=stream.getvalue())
            await self.data_access.chat_artifact_accessor.write(artifact)

            # Add image URL to be displayed in the next response
            image_url = self.data_access.chat_artifact_accessor.get_url(artifact_id)
            logger.info(f"image_url: {image_url}")
            self.chat_ctx.display_blob_urls.append(image_url)
            self.chat_ctx.display_image_urls.append(image_url)
            self.chat_ctx.output_data.append({"filename": artifact_id.filename, "type": "CT image"})
