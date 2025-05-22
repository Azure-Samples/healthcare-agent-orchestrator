# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os

from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
from autogen_agentchat.teams import MagenticOneGroupChat
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient
from semantic_kernel.agents import Agent, AgentGroupChat

from data_models.app_context import AppContext


def convert_tools(agent: Agent):
    tools = []
    for plugin in agent.kernel.plugins.values():
        for function in plugin.functions.values():
            tools.append(function.method)

    return tools


def create_magentic_chat(chat: AgentGroupChat, app_context: AppContext, input_func) -> MagenticOneGroupChat:
    agent_config = app_context.all_agent_configs
    az_model_client = AzureOpenAIChatCompletionClient(
        azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
        model="gpt-4o",
        api_version="2024-10-21",
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_ad_token_provider=app_context.cognitive_services_token_provider,
    )

    assistants = [
        AssistantAgent(agent.name, model_client=az_model_client, tools=convert_tools(agent),
                       system_message=agent.instructions, description=next((
                           config["description"]
                           for config in agent_config if agent.name == config["name"]
                       ), agent.name))
        for agent in chat.agents
    ]

    user_proxy = UserProxyAgent(name="user",
                                description="The user. As a last resort, when all else has been tried, we can ask the user for information.", input_func=input_func)
    assistants.append(
        user_proxy
    )

    team = MagenticOneGroupChat(assistants, model_client=az_model_client, max_turns=50)
    return team
