# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import logging
import uuid
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from semantic_kernel.contents import AuthorRole, ChatMessageContent, TextContent
from services.patient_context_service import PatientContextService, PATIENT_CONTEXT_PREFIX
from services.patient_context_analyzer import PatientContextAnalyzer

from data_models.app_context import AppContext

import group_chat

logger = logging.getLogger(__name__)


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles datetime objects."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class MessageRequest(BaseModel):
    content: str
    sender: str
    mentions: Optional[List[str]] = None
    channelData: Optional[Dict] = None


class Message(BaseModel):
    id: str
    content: str
    sender: str
    timestamp: datetime
    isBot: bool
    mentions: Optional[List[str]] = None

    def dict(self, *args, **kwargs):
        """Override dict method to handle datetime serialization."""
        d = super().dict(*args, **kwargs)
        if isinstance(d.get('timestamp'), datetime):
            d['timestamp'] = d['timestamp'].isoformat()
        return d


class MessageResponse(BaseModel):
    message: Message
    error: Optional[str] = None


class MessagesResponse(BaseModel):
    messages: List[Message]
    error: Optional[str] = None


class AgentsResponse(BaseModel):
    agents: List[str]
    error: Optional[str] = None


def create_json_response(content, headers=None):
    """Create a JSONResponse with proper datetime handling."""
    return JSONResponse(
        content=content,
        headers=headers or {},
        encoder=DateTimeEncoder
    )


def chats_routes(app_context: AppContext):
    router = APIRouter()

    # Extract needed values from app_context
    agent_config = app_context.all_agent_configs
    data_access = app_context.data_access

    # Initialize patient context service with both accessors
    analyzer = PatientContextAnalyzer(token_provider=app_context.cognitive_services_token_provider)
    patient_context_service = PatientContextService(
        analyzer=analyzer,
        registry_accessor=app_context.data_access.patient_context_registry_accessor,
        context_accessor=app_context.data_access.chat_context_accessor
    )

    # Find the facilitator agent
    facilitator_agent = next((agent for agent in agent_config if agent.get("facilitator")), agent_config[0])
    facilitator = facilitator_agent["name"]

    def _get_system_patient_context_json(chat_context) -> str | None:
        """Extract the JSON payload from the current PATIENT_CONTEXT_JSON system message."""
        for msg in chat_context.chat_history.messages:
            if msg.role == AuthorRole.SYSTEM:
                # Handle both string content and itemized content
                content = msg.content
                if isinstance(content, str):
                    text = content
                else:
                    # Try to extract from items if content is structured
                    items = getattr(msg, "items", None) or getattr(content, "items", None)
                    if items:
                        parts = []
                        for item in items:
                            item_text = getattr(item, "text", None) or getattr(item, "content", None)
                            if item_text:
                                parts.append(str(item_text))
                        text = "".join(parts) if parts else str(content) if content else ""
                    else:
                        text = str(content) if content else ""

                if text and text.startswith(PATIENT_CONTEXT_PREFIX):
                    # Extract JSON after "PATIENT_CONTEXT_JSON:"
                    json_part = text[len(PATIENT_CONTEXT_PREFIX):].strip()
                    if json_part.startswith(":"):
                        json_part = json_part[1:].strip()
                    return json_part if json_part else None
        return None

    def _append_pc_ctx_display(base: str, chat_context) -> str:
        """Append patient context information to the message for display."""
        # Avoid double-tagging
        if "\nPC_CTX" in base or "\n*PT_CTX:*" in base:
            return base

        # Get the actual injected system patient context JSON
        json_payload = _get_system_patient_context_json(chat_context)

        if not json_payload:
            return base

        # Format the JSON payload into a simple, readable Markdown string
        try:
            obj = json.loads(json_payload)

            lines = ["\n\n---", "\n*PT_CTX:*"]
            if obj.get("patient_id"):
                lines.append("- **Patient ID:** `%s`" % obj['patient_id'])
            if obj.get("conversation_id"):
                lines.append("- **Conversation ID:** `%s`" % obj['conversation_id'])

            if obj.get("all_patient_ids"):
                active_id = obj.get("patient_id")
                ids_str = ", ".join("`%s`%s" % (p, ' (active)' if p == active_id else '')
                                    for p in obj["all_patient_ids"])
                lines.append("- **Session Patients:** %s" % ids_str)

            if not obj.get("patient_id"):
                lines.append("- *No active patient.*")

            # Only add the block if there's something to show besides the header
            if len(lines) > 2:
                formatted_text = "\n".join(lines)
                return "%s%s" % (base, formatted_text)
            else:
                return base

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse patient context JSON: %s", e)
            # Fallback to raw if JSON is malformed, but keep it simple
            return "%s\n\n---\n*PT_CTX (raw):* `%s`" % (base, json_payload)

    async def _handle_clear_command(content: str, chat_context) -> bool:
        """Handle patient context clear commands."""
        content_lower = content.lower().strip()
        if content_lower in ["clear", "clear patient", "clear context", "clear patient context"]:
            logger.info("Processing clear command for conversation: %s", chat_context.conversation_id)

            # Archive everything before clearing
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
            archive_folder = "archive/%s" % timestamp

            try:
                logger.info("Starting archive to folder: %s", archive_folder)

                # Archive session context
                await data_access.chat_context_accessor.archive_to_folder(chat_context.conversation_id, None, archive_folder)
                logger.info("Archived session context to %s", archive_folder)

                # Archive ALL patient contexts from registry
                try:
                    patient_registry, _ = await patient_context_service.registry_accessor.read_registry(chat_context.conversation_id)
                    if patient_registry:
                        for patient_id in patient_registry.keys():
                            await data_access.chat_context_accessor.archive_to_folder(chat_context.conversation_id, patient_id, archive_folder)
                            logger.info("Archived patient context for %s to %s", patient_id, archive_folder)
                except Exception as registry_error:
                    logger.warning("Could not read registry for archiving patient contexts: %s", registry_error)
                    # Fallback: use patient_contexts from chat_context if available
                    if hasattr(chat_context, 'patient_contexts') and chat_context.patient_contexts:
                        for patient_id in chat_context.patient_contexts.keys():
                            await data_access.chat_context_accessor.archive_to_folder(chat_context.conversation_id, patient_id, archive_folder)
                            logger.info("Archived patient context for %s to %s (fallback)", patient_id, archive_folder)

                # Archive patient registry
                await patient_context_service.registry_accessor.archive_registry(chat_context.conversation_id)
                logger.info("Archived patient registry for %s", chat_context.conversation_id)

                # Clear chat context
                chat_context.patient_context = None
                if hasattr(chat_context, 'patient_contexts'):
                    chat_context.patient_contexts.clear()
                chat_context.chat_history.messages.clear()
                chat_context.patient_id = None

                logger.info("Successfully archived and cleared all contexts to %s", archive_folder)
                return True

            except Exception as e:
                logger.error("Failed to archive contexts during clear: %s", e)
                # Still clear the context even if archiving fails
                chat_context.patient_context = None
                if hasattr(chat_context, 'patient_contexts'):
                    chat_context.patient_contexts.clear()
                chat_context.chat_history.messages.clear()
                chat_context.patient_id = None
                return True

        return False

    @router.get("/api/agents", response_model=AgentsResponse)
    async def get_available_agents():
        """Returns a list of all available agents that can be mentioned in messages."""
        try:
            agent_names = [agent["name"] for agent in agent_config]
            return AgentsResponse(agents=agent_names)
        except Exception as e:
            logger.error("Error getting agents: %s", e)
            return AgentsResponse(agents=[], error=str(e))

    @router.websocket("/api/ws/chats/{chat_id}/messages")
    async def websocket_chat_endpoint(websocket: WebSocket, chat_id: str):
        """WebSocket endpoint with patient isolation support."""
        await websocket.accept()
        logger.info("WebSocket connection established for chat: %s", chat_id)

        try:
            while True:
                data = await websocket.receive_json()
                content = data.get("content", "").strip()

                if not content:
                    await websocket.send_json({"error": "Empty message content"})
                    continue

                try:
                    # STEP 1: Load session context
                    chat_context = await data_access.chat_context_accessor.read(chat_id, None)
                    logger.info("Loaded session context for: %s", chat_id)

                    # STEP 2: Handle clear commands BEFORE patient context processing
                    if await _handle_clear_command(content, chat_context):
                        clear_message = Message(
                            id=str(uuid.uuid4()),
                            content="The conversation has been cleared. How can I assist you today?",
                            sender="Orchestrator",
                            timestamp=datetime.now(timezone.utc),
                            isBot=True,
                            mentions=[]
                        )
                        await websocket.send_json(clear_message.dict())
                        await websocket.send_json({"type": "done"})

                        # Save to appropriate context file
                        await data_access.chat_context_accessor.write(chat_context)
                        continue

                    # STEP 3: Patient context decision and application
                    try:
                        decision, timing = await patient_context_service.decide_and_apply(content, chat_context)
                        logger.info("Patient context decision: %s | Patient: %s", decision, chat_context.patient_id)
                    except Exception as e:
                        logger.warning("Error applying patient context: %s", e)
                        decision = "NONE"

                    # STEP 4: Handle special decision outcomes
                    if decision == "NEEDS_PATIENT_ID":
                        error_message = Message(
                            id=str(uuid.uuid4()),
                            content="I need a patient ID to proceed. Please provide the patient ID in the format 'patient_X' (e.g., 'start tumor board review for patient_4').",
                            sender="Orchestrator",
                            timestamp=datetime.now(timezone.utc),
                            isBot=True,
                            mentions=[]
                        )
                        await websocket.send_json(error_message.dict())
                        await websocket.send_json({"type": "done"})
                        continue

                    # STEP 5: If active patient exists, load ONLY that patient's isolated context file
                    if chat_context.patient_id:
                        try:
                            isolated_ctx = await data_access.chat_context_accessor.read(chat_id, chat_context.patient_id)
                            if isolated_ctx and isolated_ctx.chat_history.messages:
                                # Replace with isolated chat history
                                chat_context.chat_history = isolated_ctx.chat_history
                                logger.info("Loaded isolated history for %s (%s messages)",
                                            chat_context.patient_id, len(isolated_ctx.chat_history.messages))
                            else:
                                logger.info("No existing history for %s, starting fresh", chat_context.patient_id)
                        except Exception as e:
                            logger.debug("Could not load isolated context for %s: %s", chat_context.patient_id, e)

                    # STEP 6: Create group chat and add user message
                    chat, chat_context = group_chat.create_group_chat(app_context, chat_context)

                    # Add user message to chat history
                    user_message = ChatMessageContent(
                        role=AuthorRole.USER,
                        items=[TextContent(text=content)]
                    )
                    chat_context.chat_history.add_message(user_message)

                    # STEP 7: Get target agent from message
                    target_agent_name = facilitator
                    if ":" in content:
                        mentioned = content.split(":", 1)[0].strip()
                        if any(agent.name.lower() == mentioned.lower() for agent in chat.agents):
                            target_agent_name = mentioned

                    target_agent = next(
                        (agent for agent in chat.agents if agent.name.lower() == target_agent_name.lower()),
                        chat.agents[0]
                    )

                    logger.info("Using agent: %s", target_agent.name)

                    if target_agent.name == facilitator:
                        target_agent = None

                    # STEP 8: Get responses
                    async for response in chat.invoke(agent=target_agent):
                        if not response or not response.content:
                            continue

                        response_content_with_pc = _append_pc_ctx_display(response.content, chat_context)

                        bot_message = Message(
                            id=str(uuid.uuid4()),
                            content=response_content_with_pc,
                            sender=response.name,
                            timestamp=datetime.now(timezone.utc),
                            isBot=True,
                            mentions=[]
                        )
                        await websocket.send_json(bot_message.dict())

                    # STEP 9: Save to appropriate context file (patient-specific OR session-only)
                    await data_access.chat_context_accessor.write(chat_context)
                    logger.info("Saved context for conversation: %s | Patient: %s", chat_id, chat_context.patient_id)

                except Exception as e:
                    logger.error("Error in WebSocket chat: %s", e)
                    await websocket.send_json({"error": str(e)})

                await websocket.send_json({"type": "done"})

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected for chat: %s", chat_id)
        except Exception as e:
            logger.error("WebSocket error: %s", e)
            try:
                await websocket.send_json({"error": str(e)})
            except Exception:
                pass

    return router
