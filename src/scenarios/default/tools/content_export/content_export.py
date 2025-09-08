# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import logging
import os
import tempfile
import textwrap
from io import BytesIO

from azure.core.exceptions import ResourceNotFoundError
from docx.shared import Inches
from docxtpl import DocxTemplate, InlineImage, RichText
from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import \
    AzureChatPromptExecutionSettings
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.functions import kernel_function
from semantic_kernel.kernel import Kernel

from data_models.chat_artifact import ChatArtifact, ChatArtifactFilename, ChatArtifactIdentifier
from data_models.chat_context import ChatContext
from data_models.data_access import DataAccess
from data_models.patient_data import PatientTimeline
from data_models.plugin_configuration import PluginConfiguration
from data_models.tumor_board_summary import ClinicalSummary, ClinicalTrial
from routes.patient_data.patient_data_routes import get_chat_artifacts_url
from utils.model_utils import model_supports_temperature

from .timeline_image import create_timeline_images_by_height

OUTPUT_DOC_FILENAME = "tumor_board_review-{}.docx"
TEMPLATE_DOC_FILENAME = "tumor_board_template.docx"

logger = logging.getLogger(__name__)


def create_plugin(plugin_config: PluginConfiguration):
    return ContentExportPlugin(
        kernel=plugin_config.kernel,
        chat_ctx=plugin_config.chat_ctx,
        data_access=plugin_config.data_access
    )


class ContentExportPlugin:
    def __init__(self, kernel: Kernel, chat_ctx: ChatContext, data_access: DataAccess):
        self.root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.chat_ctx = chat_ctx
        self.data_access = data_access
        self.kernel = kernel

    @kernel_function()
    async def export_to_word_doc(
        self,
        patient_gender: str,
        patient_age: str,
        medical_history: str,
        social_history: str,
        cancer_type: str,
        ct_scan_findings: list[str],
        x_ray_findings: list[str],
        pathology_findings: list[str],
        treatment_plan: str,
        clinical_trials: list[ClinicalTrial],
    ) -> str:
        """
        Generate Word document.

        Args:
            patient_gender (str): patient gender.
            patient_age (str): patient age.
            medical_history (str): Summarized medical history in 100 words or less.
            social_history (str): Summarized social history in 100 words or less.
            cancer_type (str): Type of cancer.
            ct_scan_findings (list[str]): CT scan findings.
            x_ray_findings (list[str]): X-ray findings.
            pathology_findings (list[str]): Pathology findings.
            treatment_plan (str): Treatment.
            clinical_trials (list[ClinicalTrial]): Eligible clinical trials.

        Returns:
            str: HTTP link
        """
        conversation_id = self.chat_ctx.conversation_id
        patient_id = self.chat_ctx.patient_id
        temp_dir = tempfile.TemporaryDirectory()

        # Load the template and render it with the provided content
        doc_template_path = os.path.join(self.root_dir, "templates", TEMPLATE_DOC_FILENAME)
        doc = DocxTemplate(doc_template_path)

        # Prepare the data for rendering
        doc_data = {
            "patient_id": patient_id,
            "patient_gender": patient_gender,
            "patient_age": patient_age,
            "medical_history": medical_history,
            "social_history": social_history,
            "cancer_type": cancer_type,
            "ct_scan_findings": ct_scan_findings,
            "x_ray_findings": x_ray_findings,
            "pathology_findings": pathology_findings,
            "treatment_plan": treatment_plan,
        }
        logger.info(f"doc_data: {doc_data}")

        try:
            # Load chat artifacts
            patient_timeline = await self._load_patient_timeline()
            research_papers = await self._load_research_papers()

            # Add additional fields to the document data
            doc_data["clinical_summary"] = await self._get_clinical_summary(patient_timeline)
            doc_data["clinical_timeline"] = await self._get_clinical_timeline(patient_timeline)
            doc_data["clinical_trials"] = self._get_clinical_trials(doc, clinical_trials)
            doc_data["research_papers"] = self._get_research_papers(doc, research_papers)

            # Add images
            doc_data["timeline_images"] = self._get_timeline_images(doc, doc_data, output_path=temp_dir.name)
            doc_data["radiology_images"] = await self._get_patient_images(doc, image_types={"x-ray image", "CT image"})
            doc_data["pathology_images"] = await self._get_patient_images(doc, image_types={"pathology image"})

            doc.render(doc_data)

            # Save the document
            artifact_id = ChatArtifactIdentifier(
                conversation_id=conversation_id,
                patient_id=patient_id,
                filename=OUTPUT_DOC_FILENAME.format(patient_id),
            )
            doc_blob_path = self.data_access.chat_artifact_accessor.get_blob_path(artifact_id)
            doc_output_url = get_chat_artifacts_url(doc_blob_path)

            stream = BytesIO()
            doc.save(stream)

            artifact = ChatArtifact(artifact_id=artifact_id, data=stream.getvalue())
            await self.data_access.chat_artifact_accessor.write(artifact)

            return f"The Word document has been successfully created. You can download it using the link below:<br><br><a href=\"{doc_output_url}\">{artifact_id.filename}</a>"
        finally:
            temp_dir.cleanup()

    async def _get_patient_images(
        self, doc: DocxTemplate, image_types: set[str], image_height: float = 1.7
    ) -> list[InlineImage]:
        conversation_id = self.chat_ctx.conversation_id
        patient_id = self.chat_ctx.patient_id
        inline_images = []

        for img in self.chat_ctx.patient_data:
            if img["type"] in image_types:
                img_stream = await self.data_access.image_accessor.read(patient_id, img["filename"])
                inline_images.append(InlineImage(doc, img_stream, height=Inches(image_height)))
        for img in self.chat_ctx.output_data:
            if img["type"] in image_types:
                artifact_id = ChatArtifactIdentifier(conversation_id, patient_id, filename=img["filename"])
                artifact = await self.data_access.chat_artifact_accessor.read(artifact_id)
                inline_images.append(InlineImage(doc, BytesIO(artifact.data), height=Inches(image_height)))

        return inline_images

    def _get_timeline_images(
        self, doc: DocxTemplate, data: dict, line_height: float = (3 / 16), line_width: int = 62,
        max_height: float = 7.0, padding: float = 1.5, output_path: str = None
    ) -> list[InlineImage]:
        # Calculate the height of summary on the first image.
        clinical_summary_lines = 0
        for item in data["clinical_summary"]:
            clinical_summary_lines += len(textwrap.wrap(item, width=line_width))
        clinical_summary_height = clinical_summary_lines * line_height

        # Subtract summary height and padding from the first image.
        image_height_first = max_height - clinical_summary_height - padding

        # Create timeline images using calculated heights.
        timeline_images = create_timeline_images_by_height(
            data["clinical_timeline"],
            height_first=image_height_first, height_after=max_height,
            output_path=output_path
        )

        return [
            InlineImage(doc, img_path) for img_path in timeline_images
        ]

    async def _get_clinical_summary(self, patient_timeline: PatientTimeline, max_entries: int = 6) -> list[str]:
        chat_history = ChatHistory()

        # Add instructions
        chat_history.add_system_message(
            "Create a clinical summary of a cancer patient for tumor board review. Summarize each entry in a concise manner, " +
            f"highlighting key points. Limit the summary to {max_entries} entries.")

        # Add patient history
        entries = [
            {
                "date": entry.date or "Not provided",
                "title": entry.title or "Untitled",
                "description": entry.description or "No description available."
            }
            for entry in patient_timeline.entries
        ]
        chat_history.add_system_message("You have access to the following patient history:\n" + json.dumps(entries))

        # Generate timeline
        # https://devblogs.microsoft.com/semantic-kernel/using-json-schema-for-structured-output-in-python-for-openai-models/
        if model_supports_temperature():
            temperature = 0.0
            logger.info(f"Using temperature setting: {temperature}")
        else:
            temperature = None
            logger.info("Model does not support temperature setting")
        settings = AzureChatPromptExecutionSettings(temperature=temperature, response_format=ClinicalSummary)
        chat_completion_service = self.kernel.get_service(service_id="default")
        chat_resp = await chat_completion_service.get_chat_message_content(chat_history=chat_history, settings=settings)

        clinical_summary = json.loads(chat_resp.content)
        return clinical_summary.get("entries", [])

    def _get_research_papers(self, doc: DocxTemplate, research_papers: dict) -> list[dict]:
        return [
            {
                "title": RichText(
                    paper["title"], color="#0000ee", underline=True,
                    url_id=doc.build_url_id(paper["url"])
                ),
                "authors": paper["authors"]
            }
            for paper in research_papers.values()
        ]

    async def _load_patient_timeline(self) -> PatientTimeline:
        artifact_id = ChatArtifactIdentifier(
            conversation_id=self.chat_ctx.conversation_id,
            patient_id=self.chat_ctx.patient_id,
            filename=ChatArtifactFilename.PATIENT_TIMELINE
        )
        artifact = await self.data_access.chat_artifact_accessor.read(artifact_id)
        return PatientTimeline.model_validate_json(artifact.data.decode("utf-8"))

    async def _load_research_papers(self) -> dict:
        artifact_id = ChatArtifactIdentifier(
            conversation_id=self.chat_ctx.conversation_id,
            patient_id=self.chat_ctx.patient_id,
            filename=ChatArtifactFilename.RESEARCH_PAPERS
        )
        try:
            artifact = await self.data_access.chat_artifact_accessor.read(artifact_id)
            return json.loads(artifact.data.decode("utf-8"))
        except ResourceNotFoundError:
            return {}

    @staticmethod
    async def _get_clinical_timeline(patient_timeline: PatientTimeline) -> list[dict]:
        clinical_timeline = []
        for entry in patient_timeline.entries:
            clinical_timeline.append({
                "date": entry.date or "yyyy-mm-dd",
                "note_title": entry.title or "Unspecified",
                "note_summary": entry.description or "No content available.",
                "note_type": entry.title or "",
            })

        return clinical_timeline

    @staticmethod
    def _get_clinical_trials(doc: DocxTemplate, clinical_trials: list[ClinicalTrial]) -> list[dict]:
        return [
            {
                "title": RichText(
                    trial.title, color="#0000ee", underline=True,
                    url_id=doc.build_url_id(trial.url)
                ),
                "summary": trial.summary
            }
            for trial in clinical_trials
        ]


# Enable command line usage for testing
if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Export content to Word document.")
    parser.add_argument("input", help="Path to the JSON file containing the data.")
    parser.add_argument("patient_data", help="Path to the JSON file containing the patient data.")
    parser.add_argument('output', default="tumor_board.docx", nargs='?', help='Path to output word document')
    args = parser.parse_args()

    with open(args.input, "r") as f:
        data = json.load(f)

    with open(args.patient_data, "r") as f:
        patient_data = json.load(f)

    chat_ctx = ChatContext("")
    chat_ctx.patient_id = data["patient_id"]
    chat_ctx.patient_data = patient_data

    plugin = ContentExportPlugin(chat_ctx)
    response = asyncio.run(plugin.export_to_word_doc(data))
    print(response)
