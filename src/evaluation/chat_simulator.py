# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import asyncio
import csv
import hashlib
import logging
import os
from datetime import datetime
from typing import Protocol

from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import \
    AzureChatPromptExecutionSettings
from semantic_kernel.connectors.ai.open_ai.services.azure_chat_completion import AzureChatCompletion
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.contents.utils.author_role import AuthorRole

from data_models.chat_context import ChatContext
from data_models.chat_context_accessor import ChatContextAccessor
from group_chat import create_group_chat

from .utils import chat_history_to_readable_text


class SimulatedUserProtocol(Protocol):
    @property
    def is_complete(self) -> bool:
        ...

    def setup(self, patient_id: str, initial_query: str, followup_questions: list[str] = None):
        """Prepare the user to start the conversation."""
        ...

    async def generate_user_message(self, chat_history: ChatHistory) -> str:
        """Generate a user message based on the chat history."""
        ...


class ProceedUser:
    def __init__(self):
        self.followup_questions = None
        self.followup_asked = False

    @property
    def is_complete(self) -> bool:
        return False

    def setup(self, patient_id: str, initial_query: str, followup_questions: list[str] = None):
        self.followup_questions = followup_questions
        self.followup_asked = False

    async def generate_user_message(self, chat_history: ChatHistory) -> str:
        if not self.followup_asked and self.followup_questions:
            self.followup_asked = True
            if self.followup_questions:
                next_question = self.followup_questions.pop(0)
                return f"Orchestrator: {next_question}"
        if not self.followup_asked and self.followup_questions:
            self.followup_asked = True
            if self.followup_questions:
                next_question = self.followup_questions.pop(0)
                return f"Orchestrator: {next_question}"
        return "Orchestrator: proceed"


class LLMUser:
    def __init__(self):
        self.chat_complete_message = "CONVERSATION COMPLETE"
        self.simulation_prompt = None
        self.is_complete = False
        self.chat_history = ChatHistory()
        self.chat_completion_service = AzureChatCompletion(
            deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
            api_version="2024-12-01-preview",
            endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        )

    def setup(self, patient_id: str, initial_query: str, followup_questions: list[str] = None):
        """Prepare the user to start the conversation."""
        followup_question_prompt = ""
        if followup_questions:
            questions_list = "\n".join(f"- {question}" for question in followup_questions)
            followup_question_prompt = f"""\
Additionally, you have these follow-up questions to ask when you think the time is right: \
"{questions_list}"

Please ask these questions in order, and wait for a complete response before moving to the next question. \
Refrain from asking each follow-up question more than once.
"""

        self.simulation_prompt = f"""\
You are an AI assistant with deep expertise in the medical domain. \
Given an objective, your goal is to interact with a group of AI agents to achieve that objective. \

All of your messages must start by addressing an agent directly. \
For example, if you simply want to approve the continuation of the agents respond with \
"Orchestrator: proceed".\

If the objectives were achieved, the followup questions asked and answered, \
and the conversation can be stopped, respond with \
"{self.chat_complete_message}".

{followup_question_prompt}

The conversation is about a patient with ID: {patient_id}. \

The conversation with the agents has already started, and the first message \
you sent to start the conversation was:

{initial_query}

Remember to ask only one follow-up question at a time, waiting for the agent's response before proceeding to the next question.
"""
        self.chat_history = ChatHistory()
        self.chat_history.add_system_message(self.simulation_prompt)
        self.is_complete = False

    async def generate_user_message(self, agent_chat_history: ChatHistory) -> str:
        """Generate a user message based on the chat history."""
        new_messages = self._extract_new_messages(agent_chat_history)
        if not new_messages:
            return ""

        self.chat_history.add_user_message(self._transform_chat_history(new_messages))

        response = await self.chat_completion_service.get_chat_message_content(
            chat_history=self.chat_history, settings=AzureChatPromptExecutionSettings()
        )

        if response.content == self.chat_complete_message:
            self.is_complete = True
            return ""

        return response.content

    def _extract_new_messages(self, chat_history: ChatHistory) -> list[ChatMessageContent]:
        """
        Extract new messages since last user message.

        Args:
            ChatHistory chat_history: The chat history containing messages from the user and agents.

        Returns:
            str: String representation of the latest messages.
        """
        last_user_message_idx = -1
        for i, message in enumerate(chat_history.messages):
            if message.role == AuthorRole.USER:
                last_user_message_idx = i

        return chat_history.messages[last_user_message_idx + 1:]

    def _transform_chat_history(self, messages: list[ChatMessageContent]) -> str:
        """
        Transforms the chat history into a format suitable for the LLM simulation.

        Args:
            ChatHistory chat_history: The chat history containing messages from the user and agents.

        Returns:
            str: String representation of the chat history.
        """
        messages_str: str = ""
        for message in messages:
            if message.role == AuthorRole.ASSISTANT:
                messages_str += f"{message.name}: {message.content}\n\n"

        return messages_str.strip()


class ChatSimulator:
    """
    Class to simulate a chat with a group of agents.

    Attributes:
        simulated_user: The simulated user to interact with the agents.
        group_chat_kwargs: Additional arguments for the group chat.
            If not given, chat_context will be created.
        patients_id: Optional list of patient IDs for the simulation.
            Can be loaded from a CSV file with `load_initial_queries`.
        initial_queries: Optional list of initial queries for the simulation.
            Can be loaded from a CSV file with `load_initial_queries`.
        followup_questions: Optional list of follow-up questions for the simulation.
            Can be loaded from a CSV file with `load_initial_queries`.
        group_followups: Whether to group follow-up questions by initial query.
        trial_count: Number of trials for each initial query.
        max_turns: Maximum number of turns in the conversation.
        output_folder_path: Path to the folder where chat history will be saved.
        save_readable_history: Whether to save a human-readable version of the chat history.
        print_messages: Whether to print messages to the console.
        raise_errors: Whether to raise errors during the simulation.
    """

    def __init__(
        self,
        simulated_user: SimulatedUserProtocol,
        group_chat_kwargs: dict,
        patients_id: list[str] = None,
        initial_queries: list[str] = None,
        trial_count: int = 2,
        max_turns: int = 5,
        followup_questions: list[list[str]] = None,
        output_folder_path: str = "chat_simulations",
        save_readable_history: bool = True,
        print_messages: bool = False,
        raise_errors: bool = False,
    ):
        self.group_chat = None
        self.chat_context = None

        # Chat simulation data
        self.patients_id = patients_id or []
        self.initial_queries = initial_queries or []
        self.followup_questions = followup_questions or []

        # Chat simulation parameters
        self.trial_count = trial_count
        self.max_turns = max_turns
        self.print_messages = print_messages

        self.simulated_user = simulated_user
        self.group_chat_kwargs = group_chat_kwargs

        self.output_folder_path = output_folder_path
        self.checkpoint_file = os.path.join(self.output_folder_path, "chat_simulation_checkpoints.txt")
        self.completed_queries = self._load_checkpoint()
        self.save_readable_history = save_readable_history

        self.raise_errors = raise_errors

        if not os.path.exists(self.output_folder_path):
            os.makedirs(self.output_folder_path, exist_ok=True)

    def setup_group_chat(self, chat_id: str, **kwargs) -> None:
        """
        Set up the group chat with the specified chat ID.

        Args:
            chat_id: The ID of the chat to be set up.
                This is ignored if chat_ctx is provided in kwargs.
            kwargs: Additional arguments to be passed to the group chat creation function.
        """
        if "chat_ctx" not in kwargs:
            kwargs["chat_ctx"] = ChatContext(chat_id)
        self.group_chat, self.chat_context = create_group_chat(**kwargs)

        return self

    def load_initial_queries(
        self,
        csv_file_path: str,
        patients_id_column: str,
        initial_queries_column: str,
        followup_column: str | None = None,
        delimiter: str = ",",
        group_followups: bool = True,
    ):
        """
        Load initial queries and follow-up questions from a CSV file without using pandas.

        Args:
            csv_file_path: Path to the CSV file containing the patient ids, initial queries and follow-up questions.
            patients_id_column: Name of the column containing patient IDs.
            initial_queries_column: Name of the column containing initial queries.
            followup_column: Name of the column containing follow-up questions.
            delimiter: Delimiter used in the CSV file (default is comma).

        Returns:
            self: Returns the instance for method chaining.
        """
        try:
            # Try UTF-8 first
            with open(csv_file_path, mode="r", encoding="utf-8") as csv_file:
                reader = csv.DictReader(csv_file, delimiter=delimiter)
                if any('\ufeff' in field for field in reader.fieldnames):
                    # If UTF-8 failed to properly read headers, try UTF-8-SIG
                    raise UnicodeError("BOM detected, retrying with utf-8-sig")

                self._process_csv_content(
                    reader=reader,
                    patients_id_column=patients_id_column,
                    initial_queries_column=initial_queries_column,
                    followup_column=followup_column,
                    group_followups=group_followups,
                )
        except UnicodeError:
            # Fall back to UTF-8-SIG if UTF-8 didn't work well
            with open(csv_file_path, mode="r", encoding="utf-8-sig") as csv_file:
                reader = csv.DictReader(csv_file, delimiter=delimiter)
                self._process_csv_content(
                    reader=reader,
                    patients_id_column=patients_id_column,
                    initial_queries_column=initial_queries_column,
                    followup_column=followup_column,
                    group_followups=group_followups,
                )

        return self

    async def simulate_chats(self):
        """Simulate chats with the specified patients and queries."""
        for patient_id, initial_query, followup_questions in zip(self.patients_id, self.initial_queries, self.followup_questions):
            checkpoint_key = self._generate_chat_unique_id(patient_id, initial_query, followup_questions)

            if checkpoint_key in self.completed_queries:
                logging.info(f"Skipping already completed conversation: {checkpoint_key}")
                continue

            for trial in range(self.trial_count):
                try:
                    logging.debug(
                        f"Setting up simulated user with initial query: {initial_query} and followups: {followup_questions}"
                    )

                    self.setup_group_chat(checkpoint_key, **self.group_chat_kwargs)

                    await self.chat(patient_id, initial_query, followup_questions, self.max_turns)
                    self.save(f"chat_context_trial{trial}_{checkpoint_key}.json",
                              save_readable_history=self.save_readable_history)
                except Exception as e:
                    logging.error(
                        f"Error during conversation with initial query: {initial_query} and followup: {followup_questions[0]}: {e}")
                    if self.raise_errors:
                        raise e
                    else:
                        continue

            # Mark the query as completed and save to the checkpoint file
            self._save_checkpoint(checkpoint_key)
            self.completed_queries.add(checkpoint_key)

        # Delete the checkpoint file after all simulations are complete
        if os.path.exists(self.checkpoint_file):
            os.remove(self.checkpoint_file)
            logging.info(f"Deleted checkpoint file: {self.checkpoint_file}")

        return self

    async def chat(self, patient_id: str, initial_query: str, followup_questions: list[str], max_turns: int):
        """
        Simulate a chat with the specified parameters.

        This method also takes care of setting up the simulated user.

        Args:
            patient_id: The ID of the patient.
            initial_query: The initial query to start the conversation.
            followup_questions: A list of follow-up questions to ask.
            max_turns: The maximum number of turns in the conversation.
        """
        self.simulated_user.setup(patient_id, initial_query, followup_questions)

        await self.send_user_message(initial_query)
        for _ in range(max_turns):

            try:
                new_user_message = await self.simulated_user.generate_user_message(self.group_chat.history)
            except Exception as e:
                print(f"Error generating user message: {e}")
                break

            if self.simulated_user.is_complete:
                logging.debug("Simulated user marked conversation as complete")
                break

            await self.send_user_message(new_user_message)

    async def send_user_message(self, message: str):
        """
        Send a user message to the group chat.

        Args:
            message: The message to be sent.

        Returns:
            self: Returns the instance for method chaining.
        """
        user_message = ChatMessageContent(role=AuthorRole.USER, content=message)
        self._print_message(user_message)
        await self.group_chat.add_chat_message(user_message)
        self.group_chat.is_complete = False

        async for response in self.group_chat.invoke():
            self._print_message(response)
            if self.group_chat.is_complete:
                break

        # Give it some time to agents to be idle again.
        await asyncio.sleep(1)

        return self

    def save(self, output_filename: str = None, save_readable_history: bool = False) -> None:
        """
        Save the chat history to a file.

        Args:
            output_filename: The name of the output file.
                The file will be saved in the output folder path.
            save_readable_history: Whether to save a human-readable version of the chat history.

        Returns:
            self: Returns the instance for method chaining.
        """
        group_chat_context = ChatContextAccessor.serialize(self.chat_context)

        if output_filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"chat_history_{timestamp}.json"

        output_file_path = os.path.join(
            self.output_folder_path,
            output_filename
        )

        with open(output_file_path, 'w', encoding="utf-8") as f:
            # Save the chat history to a file
            f.write(group_chat_context)

        if save_readable_history:
            messages = chat_history_to_readable_text(self.group_chat.history)
            readable_filename = output_file_path.replace(".json", "_readable.txt")
            with open(readable_filename, 'w', encoding="utf-8") as f:
                f.write(messages)

        return self

    def _print_message(self, message: ChatMessageContent):
        """Print the message to the console if print_messages is enabled."""
        if self.print_messages:
            logging.info(f"# {message.role} - {message.name or '*'}: '{message.content}'")

    def _process_csv_content(
        self,
        reader: csv.DictReader,
        patients_id_column: str,
        initial_queries_column: str,
        followup_column: str | None,
        group_followups: bool,
    ):
        """Process CSV content after file is opened with proper encoding.

        This method populates the patients_id, initial_queries, and followup_questions attributes
        based on the CSV file content.

        Args:
            reader: The CSV reader object.
            patients_id_column: Name of the column containing patient IDs.
            initial_queries_column: Name of the column containing initial queries.
            followup_column: Name of the column containing follow-up questions.

        Raises:
            ValueError: If the specified columns are not found in the CSV file.
        """
        if initial_queries_column not in reader.fieldnames:
            raise ValueError(f"Column '{initial_queries_column}' not found in the CSV file.")

        if patients_id_column not in reader.fieldnames:
            raise ValueError(f"Columns '{patients_id_column}' not found in the CSV file.")

        followup_column_available = followup_column is not None and followup_column in reader.fieldnames

        patient_id_questions_map: dict[str, dict[str, list]] = {}
        for row in reader:
            patient_id = row[patients_id_column].strip()
            if patient_id not in patient_id_questions_map:
                patient_id_questions_map[patient_id] = {}

            initial_query = row[initial_queries_column].strip()
            if initial_query not in patient_id_questions_map[patient_id]:
                patient_id_questions_map[patient_id][initial_query] = []

            followup_question = ""
            if followup_column_available:
                followup_question = row[followup_column].strip()

            # This may include duplicated follow-up questions, which is fine if we are grouping them.
            patient_id_questions_map[patient_id][initial_query].append(followup_question)

        self.patients_id = []
        self.initial_queries = []
        self.followup_questions = []

        for patient_id, queries in patient_id_questions_map.items():
            if group_followups:
                # Group follow-ups by initial query
                for initial_query, followups in queries.items():
                    self.patients_id.append(patient_id)
                    self.initial_queries.append(initial_query)
                    self.followup_questions.append(followups)
            else:
                # Treat each follow-up as a separate conversation
                for initial_query, followups in queries.items():
                    deduplicated_followups = set(followups)
                    for followup in deduplicated_followups:
                        self.patients_id.append(patient_id)
                        self.initial_queries.append(initial_query)
                        self.followup_questions.append([followup])

    def _load_checkpoint(self) -> set:
        """Load completed queries from the checkpoint file."""
        if os.path.exists(self.checkpoint_file):
            with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                return set(line.strip() for line in f.readlines())
        return set()

    def _save_checkpoint(self, query: str):
        """Save a completed query to the checkpoint file."""
        with open(self.checkpoint_file, "w+", encoding="utf-8") as f:
            f.write(f"{query}\n")

    def _generate_chat_unique_id(self, patient_id: str, initial_query: str, followup_questions: list[str]) -> str:
        """Generate a unique ID for the chat based on patient ID, initial query, and follow-up questions."""
        return hashlib.sha256(
            f"{patient_id}{initial_query}{"".join(followup_questions)}{type(self.simulated_user).__name__}".encode()).hexdigest()
