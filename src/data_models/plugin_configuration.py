# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from semantic_kernel import Kernel

from data_models.chat_context import ChatContext
from data_models.data_access import DataAccess


@dataclass(frozen=True)
class PluginConfiguration:
    """
    Configuration for a plugin in the Semantic Kernel environment. Attributes are read-only and set during initialization.

    Attributes:
    -----------
    kernel : Kernel
        The main entry point of Semantic Kernel. It provides the ability to run functions and manage filters, plugins, and AI services.
    chat_ctx : ChatContext
        A composite object that contains chat history and chat session data.
    agent_config : dict
        The configuration of the agent. Loaded from agents.yaml file.
    data_access : DataAccess
        A composite object that contains data access objects for read/write data to storage.
    """
    kernel: Kernel
    chat_ctx: ChatContext
    agent_config: dict
    data_access: DataAccess
    azureml_token_provider: Callable[[], Coroutine[Any, Any, str]]
