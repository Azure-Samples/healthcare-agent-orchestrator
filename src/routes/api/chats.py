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

from semantic_kernel.contents import AuthorRole, ChatMessageContent
from services.patient_context_service import PatientContextService, PATIENT_CONTEXT_PREFIX
from services.patient_context_analyzer import PatientContextAnalyzer

from data_models.app_context import AppContext
import group_chat

logger = logging.getLogger(__name__)

# Custom JSON encoder that handles datetime


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

# Pydantic models for request/response


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
        # Override dict method to handle datetime serialization
        d = super().dict(*args, **kwargs)
        # Convert datetime to ISO format string
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

# Create a helper function to create JSON responses with datetime handling


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

    # Initialize patient context service
    analyzer = PatientContextAnalyzer(token_provider=app_context.cognitive_services_token_provider)
    patient_context_service = PatientContextService(analyzer=analyzer)

    # Find the facilitator agent
    facilitator_agent = next((agent for agent in agent_config if agent.get("facilitator")), agent_config[0])
    facilitator = facilitator_agent["name"]

    def _append_pc_ctx_system(chat_history_messages: List[ChatMessageContent], patient_context: str) -> None:
        """Append patient context to chat history at position 0 (system message)."""
        if len(chat_history_messages) > 0 and chat_history_messages[0].role == AuthorRole.SYSTEM:
            # Update existing system message
            existing_content = chat_history_messages[0].content
            if PATIENT_CONTEXT_PREFIX not in existing_content:
                chat_history_messages[0].content = f"{existing_content}\n\n{patient_context}"
        else:
            # Insert new system message at position 0
            system_message = ChatMessageContent(
                role=AuthorRole.SYSTEM,
                content=patient_context
            )
            chat_history_messages.insert(0, system_message)

    def _get_system_patient_context_json(chat_context) -> str | None:
        """Extract the JSON payload from the current PATIENT_CONTEXT_JSON system message."""
        # Fix: Use .messages instead of .history
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
                lines.append(f"- **Patient ID:** `{obj['patient_id']}`")
            if obj.get("conversation_id"):
                lines.append(f"- **Conversation ID:** `{obj['conversation_id']}`")

            if obj.get("all_patient_ids"):
                active_id = obj.get("patient_id")
                ids_str = ", ".join(f"`{p}`{' (active)' if p == active_id else ''}" for p in obj["all_patient_ids"])
                lines.append(f"- **Session Patients:** {ids_str}")

            summary_raw = obj.get("chat_summary", "")
            if summary_raw and summary_raw.strip():
                # Check if it's the default "no specific information" message
                if "No specific information was discussed" in summary_raw:
                    lines.append(f"- **Summary:** *Building patient context...*")
                else:
                    # Clean up summary for display
                    summary = summary_raw.replace('\n', ' ').strip()
                    lines.append(f"- **Summary:** *{summary}*")
            else:
                lines.append(f"- **Summary:** *Building patient context...*")

            if not obj.get("patient_id"):
                lines.append("- *No active patient.*")

            # Only add the block if there's something to show besides the header
            if len(lines) > 2:
                formatted_text = "\n".join(lines)
                logger.debug(f"Appended patient context to message | Patient: {obj.get('patient_id')}")
                return f"{base}{formatted_text}"
            else:
                return base

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse patient context JSON: {e}")
            # Fallback to raw if JSON is malformed, but keep it simple
            return f"{base}\n\n---\n*PT_CTX (raw):* `{json_payload}`"

    def _format_patient_context_json(patient_context: str) -> str:
        """Convert patient context to JSON format for system message."""
        return json.dumps({
            "patient_context": patient_context,
            "instruction": "Use this patient context to provide relevant responses. Always consider the patient's current medical status, history, and any active conditions when responding."
        }, indent=2)

    async def _handle_clear_command(content: str, chat_context) -> bool:
        """Handle patient context clear commands."""
        content_lower = content.lower().strip()
        if content_lower in ["clear", "clear patient", "clear context", "clear patient context"]:
            # Clear patient context
            chat_context.patient_context = None
            logger.info("Patient context cleared via WebSocket clear command")
            return True
        return False

    @router.get("/api/agents", response_model=AgentsResponse)
    async def get_available_agents():
        """
        Returns a list of all available agents that can be mentioned in messages.
        """
        try:
            # Extract agent names from the agent_config
            agent_names = [agent["name"] for agent in agent_config if "name" in agent]

            # Return the list of agent names
            return JSONResponse(
                content={"agents": agent_names, "error": None}
            )
        except Exception as e:
            logger.exception(f"Error getting available agents: {e}")
            return JSONResponse(
                content={"agents": [], "error": str(e)},
                status_code=500
            )

    @router.websocket("/api/ws/chats/{chat_id}/messages")
    async def websocket_chat_endpoint(websocket: WebSocket, chat_id: str):
        """WebSocket endpoint for streaming chat messages"""
        try:
            await websocket.accept()
            logger.info(f"WebSocket connection established for chat: {chat_id}")

            # Wait for the first message from the client
            client_message = await websocket.receive_json()
            logger.info(f"Received message over WebSocket: {client_message}")

            # Extract message content, sender and mentions
            content = client_message.get("content", "")
            sender = client_message.get("sender", "User")
            mentions = client_message.get("mentions", [])

            # Try to read existing chat context or create a new one if it doesn't exist
            try:
                chat_context = await data_access.chat_context_accessor.read(chat_id)
            except:
                # If the chat doesn't exist, create a new one
                chat_context = await data_access.chat_context_accessor.create_new(chat_id)

            # Handle clear commands
            if await _handle_clear_command(content, chat_context):
                # Send confirmation message
                clear_message = Message(
                    id=str(uuid.uuid4()),
                    content="Patient context has been cleared.",
                    sender="System",
                    timestamp=datetime.now(timezone.utc),
                    isBot=True,
                    mentions=[]
                )
                await websocket.send_json(clear_message.dict())
                await websocket.send_json({"type": "done"})

                # Save updated context
                await data_access.chat_context_accessor.write(chat_context)
                return

            # Add user message to history
            chat_context.chat_history.add_user_message(content)

            # Apply patient context using the service - FIX: Use correct method signature
            try:
                decision, timing = await patient_context_service.decide_and_apply(
                    content,  # user_text parameter
                    chat_context  # chat_ctx parameter
                )

                logger.info(f"Patient context decision: {decision}, timing: {timing}")

            except Exception as e:
                logger.warning(f"Error applying patient context to WebSocket message: {e}")
                # Continue without patient context

            # Create group chat instance
            chat, chat_context = group_chat.create_group_chat(app_context, chat_context)

            # Process the message - determine target agent based on mentions
            target_agent_name = facilitator  # Default to facilitator agent

            if mentions and len(mentions) > 0:
                # Use the first mentioned agent
                target_agent_name = mentions[0]

            # Find the agent by name
            target_agent = next(
                (agent for agent in chat.agents if agent.name.lower() == target_agent_name.lower()),
                chat.agents[0]  # Fallback to first agent
            )

            logger.info(f"Using agent: {target_agent.name} to respond to WebSocket message")

            # Check if the agent is the facilitator
            if target_agent.name == facilitator:
                target_agent = None  # Force facilitator mode when target is the facilitator

            response_sent = False

            # Get responses from the target agent
            async for response in chat.invoke(agent=target_agent):
                # Skip responses with no content
                if not response or not response.content:
                    continue

                # Add patient context display to response content
                response_content_with_pc = _append_pc_ctx_display(response.content, chat_context)

                # Create bot response message for each response
                bot_message = Message(
                    id=str(uuid.uuid4()),
                    content=response_content_with_pc,  # Use content with PC_CTX display
                    sender=response.name,
                    timestamp=datetime.now(timezone.utc),
                    isBot=True,
                    mentions=[]
                )

                # Convert to dict for JSON serialization
                message_dict = bot_message.dict()

                # Send message over WebSocket
                await websocket.send_json(message_dict)

            # Save chat context after all messages are processed
            await data_access.chat_context_accessor.write(chat_context)

            # Send done signal
            await websocket.send_json({"type": "done"})

        except WebSocketDisconnect:
            logger.info(f"WebSocket client disconnected from chat: {chat_id}")
        except Exception as e:
            logger.exception(f"Error in WebSocket chat: {e}")
            try:
                # Try to send error message to client
                await websocket.send_json({"error": str(e)})
                await websocket.send_json({"type": "done"})
            except:
                pass

    return router
