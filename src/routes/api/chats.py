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
    
    # Find the facilitator agent
    facilitator_agent = next((agent for agent in agent_config if agent.get("facilitator")), agent_config[0])
    facilitator = facilitator_agent["name"]
    
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
            
            # Add user message to history
            chat_context.chat_history.add_user_message(content)
            
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
                    
                # Create bot response message for each response
                bot_message = Message(
                    id=str(uuid.uuid4()),
                    content=response.content,
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
