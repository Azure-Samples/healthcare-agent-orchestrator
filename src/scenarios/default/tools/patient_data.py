# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import logging
import os
import re
import textwrap
from uuid import uuid4

from azure.core.exceptions import ResourceNotFoundError
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import \
    AzureChatPromptExecutionSettings
from semantic_kernel.connectors.ai.open_ai.services.azure_chat_completion import AzureChatCompletion
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.functions import kernel_function

from data_models.chat_artifact import ChatArtifact, ChatArtifactFilename, ChatArtifactIdentifier
from data_models.chat_context import ChatContext
from data_models.data_access import DataAccess
from data_models.patient_data import PatientDataAnswer, PatientTimeline
from data_models.plugin_configuration import PluginConfiguration
from routes.views.patient_data_answer_routes import get_patient_data_answer_source_url
from routes.views.patient_timeline_routes import get_patient_timeline_entry_source_url

logger = logging.getLogger(__name__)


def create_plugin(plugin_config: PluginConfiguration):
    return PatientDataPlugin(
        plugin_config.kernel,
        plugin_config.chat_ctx,
        plugin_config.data_access
    )


def _is_valid(input: str) -> bool:
    pattern = "\\w+[\\s\\w\\-\\.]*"
    return bool(re.match(pattern, input))


class PatientDataPlugin:
    def __init__(self, kernel: Kernel, chat_ctx: ChatContext, data_access: DataAccess):
        self.chat_ctx = chat_ctx
        self.root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.kernel = kernel
        self.data_access = data_access

    @kernel_function(
        description="Load patient images and reports from data store. The output will contain a list of files with name and type."
    )
    async def load_patient_data(self, patient_id: str) -> str:
        if not _is_valid(patient_id):
            return "Invalid patient ID"

        try:
            self.chat_ctx.patient_id = patient_id

            # Load patient metadata
            clinical_note_metadatas = await self.data_access.clinical_note_accessor.get_metadata_list(patient_id)
            image_metadatas = await self.data_access.image_accessor.get_metadata_list(patient_id)
            self.chat_ctx.patient_data = clinical_note_metadatas + image_metadatas

            response = json.dumps({
                "clinical notes": clinical_note_metadatas,
                "images": image_metadatas
            })
            logger.info(f"Loaded patient data for {patient_id}: {response}")
            return response
        except:
            # try to retrieve valid patients:
            patients = await self.data_access.clinical_note_accessor.get_patients()
            logger.exception(f"Error loading patient data for {patient_id}")
            return f"Invalid patient ID: {patient_id}. Choose from following patient IDs: {", ".join(patients)}"

    @kernel_function()
    async def create_timeline(self, patient_id: str) -> str:
        """
        Creates a clinical timeline for a patient.

        Args:  
            patient_id (str): The patient ID to be used.

        Returns:  
            str: The clinical timeline of the patient.
        """
        conversation_id = self.chat_ctx.conversation_id
        files = await self.data_access.clinical_note_accessor.read_all(patient_id)

        chat_completion_service: AzureChatCompletion = self.kernel.get_service(service_id="default")
        chat_history = ChatHistory()

        # Add instructions
        chat_history.add_system_message(
            textwrap.dedent("""
                Create a Patient Timeline: Organize the patient data in chronological order to create a
                clear timeline of the patient's medical history and treatment. Use the provided clinical
                notes. The timeline will be used as background for a molecular tumor board discussion.
                Be sure to include all relevant details such as:
                - Initial presentation and diagnosis
                - All biomarkers
                - Dates, doseages, and cycles of treatments
                - Surgeries
                - Biopsies or other pathology results
                - Response to treatment, including dates and details of imaging used to evaluate response
                - Any other relevant details
                Be sure to include an overview of patient demographics and a summary of current status.
                Add the referenced clinical note as a source. A source may contain multiple sentences.
            """).strip()
        )

        # Add patient history
        chat_history.add_system_message("You have access to the following patient history:\n" + json.dumps(files))

        # Generate timeline
        # https://devblogs.microsoft.com/semantic-kernel/using-json-schema-for-structured-output-in-python-for-openai-models/
        settings = self._get_chat_prompt_exec_settings(PatientTimeline)
        chat_resp = await chat_completion_service.get_chat_message_content(chat_history=chat_history, settings=settings)

        # Parse the response to PatientTimeline object
        timeline = PatientTimeline.model_validate_json(chat_resp.content)
        timeline.patient_id = patient_id

        # Save patient timeline
        artifact_id = ChatArtifactIdentifier(
            conversation_id=self.chat_ctx.conversation_id,
            patient_id=patient_id,
            filename=ChatArtifactFilename.PATIENT_TIMELINE
        )
        artifact = ChatArtifact(artifact_id, data=chat_resp.content.encode('utf-8'))
        await self.data_access.chat_artifact_accessor.write(artifact)

        # Format the timeline for display
        response = ""
        indent = " " * 4
        for entry_index, entry in enumerate(timeline.entries):
            response += f"- {entry.date}: {entry.title}\n"
            response += f"{indent}- {entry.description}\n"
            for src_idx, src in enumerate(entry.sources):
                note_url = get_patient_timeline_entry_source_url(conversation_id, patient_id, entry_index, src_idx)
                source_text = " ".join(src.sentences) if src.sentences else "No text provided"
                shortened_source_text = textwrap.shorten(source_text, width=160, placeholder="\u2026")
                response += f"{indent}- Source: [{shortened_source_text}]({note_url})\n"
        logger.info(f"Created timeline for {patient_id}: {response}")

        return response

    @kernel_function()
    async def process_prompt(self, patient_id: str, prompt: str) -> str:
        """  
        Processes the given prompt using the large text corpus and generates a response.  
        The prompt is passed to a LLM as a system prompt. 

        Args:  
            prompt (str): The prompt to be processed as the system prompt.
            patient_id (str): The patient ID to be used.

        Returns:  
            str: The generated response based on the large text and the given prompt.  
        """
        if not _is_valid(patient_id):
            return "Invalid patient ID"

        conversation_id = self.chat_ctx.conversation_id
        files = await self.data_access.clinical_note_accessor.read_all(patient_id)

        chat_history = ChatHistory()
        chat_history.add_system_message(
            "When answering questions, always base the answer strictly on the patient's history. You may infer the " +
            "answer if it is not directly available. Provide your reasoning if you have inferred the answer. Use the " +
            "provided clinical notes. Add the referenced clinical notes as sources. A source may contain " +
            "multiple sentences.")
        chat_history.add_system_message("You have access to the following patient history:\n" + json.dumps(files))
        chat_history.add_system_message(prompt)

        chat_completion_service: AzureChatCompletion = self.kernel.get_service(service_id="default")
        settings = self._get_chat_prompt_exec_settings(PatientDataAnswer)
        chat_resp = await chat_completion_service.get_chat_message_content(chat_history=chat_history, settings=settings)

        # Parse the response to PatientDataAnswer object
        answer = PatientDataAnswer.model_validate_json(chat_resp.content)
        answer_id = str(uuid4())

        # Save PatientDataAnswer
        artifact_id = ChatArtifactIdentifier(
            conversation_id=self.chat_ctx.conversation_id,
            patient_id=patient_id,
            filename=ChatArtifactFilename.PATIENT_DATA_ANSWERS
        )
        try:
            answers_artifact = await self.data_access.chat_artifact_accessor.read(artifact_id)
            answers = json.loads(answers_artifact.data.decode('utf-8'))
            answers[answer_id] = chat_resp.content
        except ResourceNotFoundError:
            answers = {answer_id: chat_resp.content}
        await self.data_access.chat_artifact_accessor.write(
            ChatArtifact(artifact_id, data=json.dumps(answers).encode('utf-8'))
        )

        # Format the timeline for display
        response = f"{answer.text}\n\n**Sources**:\n"
        indent = " " * 4
        for src_idx, src in enumerate(answer.sources):
            note_url = get_patient_data_answer_source_url(conversation_id, patient_id, answer_id, src_idx)
            source_text = " ".join(src.sentences) if src.sentences else "No text provided"
            shortened_source_text = textwrap.shorten(source_text, width=160, placeholder="\u2026")
            response += f"{indent}- Source: [{shortened_source_text}]({note_url})\n"
        logger.info(f"Created answer for {patient_id}: {response}")

        return response

    @staticmethod
    def _get_chat_prompt_exec_settings(response_format) -> AzureChatPromptExecutionSettings:
        return AzureChatPromptExecutionSettings(
            response_format=response_format,
            temperature=0.0,
            seed=42
        )
