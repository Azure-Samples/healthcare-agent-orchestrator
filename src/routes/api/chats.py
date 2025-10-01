# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

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
        d = super().dict(*args, **kwargs)
        if isinstance(d.get("timestamp"), datetime):
            d["timestamp"] = d["timestamp"].isoformat()
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
    return JSONResponse(
        content=content,
        headers=headers or {},
        encoder=DateTimeEncoder
    )


def chats_routes(app_context: AppContext):
    router = APIRouter()
    agent_config = app_context.all_agent_configs
    data_access = app_context.data_access

    analyzer = PatientContextAnalyzer(token_provider=app_context.cognitive_services_token_provider)
    patient_context_service = PatientContextService(
        analyzer=analyzer,
        registry_accessor=app_context.data_access.patient_context_registry_accessor,
        context_accessor=app_context.data_access.chat_context_accessor
    )

    facilitator_agent = next((a for a in agent_config if a.get("facilitator")), agent_config[0])
    facilitator = facilitator_agent["name"]

    # ===== Legacy helper retained (now always sees freshly injected snapshot) =====
    def _get_system_patient_context_json(chat_context) -> str | None:
        """Return JSON payload from most recent (first-in-list after injection) PATIENT_CONTEXT system message."""
        for msg in reversed(chat_context.chat_history.messages):
            if msg.role == AuthorRole.SYSTEM:
                # Extract text
                if hasattr(msg, "items") and msg.items:
                    text = getattr(msg.items[0], "text", "") or ""
                else:
                    text = getattr(msg, "content", "") or ""
                if text.startswith(PATIENT_CONTEXT_PREFIX):
                    json_part = text[len(PATIENT_CONTEXT_PREFIX):].lstrip()
                    if json_part.startswith(":"):
                        json_part = json_part[1:].lstrip()
                    return json_part or None
        return None

    def _append_pc_ctx_display(base: str, chat_context) -> str:
        """Append user-friendly PT_CTX block for UI (optional cosmetic)."""
        json_payload = _get_system_patient_context_json(chat_context)
        if not json_payload:
            return base
        try:
            obj = json.loads(json_payload)
        except Exception:
            return base

        pid = obj.get("patient_id")
        all_pids = obj.get("all_patient_ids") or []
        convo_id = obj.get("conversation_id")

        # Build lines with explicit leading newlines for clarity
        lines: list[str] = []
        lines.append("\n\n---")
        lines.append("\n*PT_CTX:*")
        if pid:
            lines.append(f"\n- **Patient ID:** `{pid}`")
        else:
            lines.append("\n- *No active patient.*")
        if all_pids:
            ids_str = ", ".join(
                f"`{p}`{' (active)' if p == pid else ''}" for p in sorted(all_pids)
            )
            lines.append(f"\n- **Session Patients:** {ids_str}")
        if convo_id:
            lines.append(f"\n- **Conversation ID:** `{convo_id}`")

        # If we only ended up with the header and separator, skip (unlikely)
        if len(lines) <= 2:
            return base

        return base + "".join(lines)

    async def _handle_clear_command(content: str, chat_context) -> bool:
        content_lower = content.lower().strip()
        if content_lower in ["clear", "clear patient", "clear context", "clear patient context"]:
            logger.info("Processing clear command for conversation: %s", chat_context.conversation_id)
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
            archive_folder = f"archive/{timestamp}"
            try:
                # Archive session
                await data_access.chat_context_accessor.archive_to_folder(chat_context.conversation_id, None, archive_folder)
                # Archive each patient file from registry
                try:
                    patient_registry, _ = await patient_context_service.registry_accessor.read_registry(chat_context.conversation_id)
                    if patient_registry:
                        for pid in patient_registry.keys():
                            await data_access.chat_context_accessor.archive_to_folder(chat_context.conversation_id, pid, archive_folder)
                except Exception:
                    if getattr(chat_context, "patient_contexts", None):
                        for pid in chat_context.patient_contexts.keys():
                            await data_access.chat_context_accessor.archive_to_folder(chat_context.conversation_id, pid, archive_folder)
                # Archive registry
                await patient_context_service.registry_accessor.archive_registry(chat_context.conversation_id)
            except Exception as e:
                logger.warning("Clear archival issues: %s", e)
            finally:
                chat_context.patient_context = None
                if hasattr(chat_context, "patient_contexts"):
                    chat_context.patient_contexts.clear()
                chat_context.chat_history.messages.clear()
                chat_context.patient_id = None
                await data_access.chat_context_accessor.write(chat_context)
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

                    # STEP 2: Clear?
                    if await _handle_clear_command(content, chat_context):
                        msg = Message(
                            id=str(uuid.uuid4()),
                            content="The conversation has been cleared. How can I assist you today?",
                            sender="Orchestrator",
                            timestamp=datetime.now(timezone.utc),
                            isBot=True
                        )
                        await websocket.send_json(msg.dict())
                        await websocket.send_json({"type": "done"})
                        continue

                    # STEP 3: Patient decision
                    try:
                        decision, timing = await patient_context_service.decide_and_apply(content, chat_context)
                        logger.info("Patient context decision=%s active=%s", decision, chat_context.patient_id)
                    except Exception as e:
                        logger.warning("Patient context decision failed: %s", e)
                        decision = "NONE"

                    # STEP 4: Special outcomes
                    if decision == "NEEDS_PATIENT_ID":
                        err = Message(
                            id=str(uuid.uuid4()),
                            content="I need a patient ID to proceed. Provide one like 'patient_4'.",
                            sender="Orchestrator",
                            timestamp=datetime.now(timezone.utc),
                            isBot=True
                        )
                        await websocket.send_json(err.dict())
                        await websocket.send_json({"type": "done"})
                        continue

                    # STEP 5: Load isolated patient history if active
                    if chat_context.patient_id:
                        try:
                            isolated = await data_access.chat_context_accessor.read(chat_id, chat_context.patient_id)
                            if isolated and isolated.chat_history.messages:
                                chat_context.chat_history = isolated.chat_history
                        except Exception as e:
                            logger.debug("Isolated load failed for %s: %s", chat_context.patient_id, e)

                    # STEP 5.5: Inject fresh ephemeral PATIENT_CONTEXT_JSON system message (rebuild from current in-memory state)
                    # Remove existing snapshot(s)
                    new_messages = []
                    for m in chat_context.chat_history.messages:
                        if not (m.role == AuthorRole.SYSTEM and hasattr(m, "items") and m.items
                                and getattr(m.items[0], "text", "").startswith(PATIENT_CONTEXT_PREFIX)):
                            new_messages.append(m)
                    chat_context.chat_history.messages = new_messages
                    snapshot = {
                        "conversation_id": chat_context.conversation_id,
                        "patient_id": chat_context.patient_id,
                        "all_patient_ids": sorted(getattr(chat_context, "patient_contexts", {}).keys()),
                        "generated_at": datetime.utcnow().isoformat() + "Z"
                    }
                    system_line = f"{PATIENT_CONTEXT_PREFIX}: {json.dumps(snapshot, separators=(',', ':'))}"
                    system_msg = ChatMessageContent(role=AuthorRole.SYSTEM, items=[TextContent(text=system_line)])
                    chat_context.chat_history.messages.insert(0, system_msg)

                    # STEP 6: Group chat & add user message
                    chat, chat_context = group_chat.create_group_chat(app_context, chat_context)
                    user_message = ChatMessageContent(role=AuthorRole.USER, items=[TextContent(text=content)])
                    chat_context.chat_history.add_message(user_message)

                    # STEP 7: Agent selection
                    target_agent_name = facilitator
                    if ":" in content:
                        candidate = content.split(":", 1)[0].strip()
                        if any(a.name.lower() == candidate.lower() for a in chat.agents):
                            target_agent_name = candidate
                    target_agent = next(
                        (a for a in chat.agents if a.name.lower() == target_agent_name.lower()),
                        chat.agents[0]
                    )
                    if target_agent.name == facilitator:
                        target_agent = None

                    # STEP 8: Invoke agents
                    async for response in chat.invoke(agent=target_agent):
                        if not response or not response.content:
                            continue

                        # Optional UI block (system snapshot already grounds LLM)
                        response_with_ctx = _append_pc_ctx_display(response.content, chat_context)

                        bot_message = Message(
                            id=str(uuid.uuid4()),
                            content=response_with_ctx,
                            sender=response.name,
                            timestamp=datetime.now(timezone.utc),
                            isBot=True
                        )
                        await websocket.send_json(bot_message.dict())

                    # STEP 9: Persist (system snapshot filtered in accessor)
                    await data_access.chat_context_accessor.write(chat_context)

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
