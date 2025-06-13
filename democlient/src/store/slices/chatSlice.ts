import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import type { Chat, Message } from '../../types';

// Define a type for tracking pending messages
interface PendingMessage {
    targetAgent: string;
    timestamp: Date;
}

interface ChatState {
    chats: Chat[];
    selectedChatId: string | null;
    isLoading: boolean;
    pendingResponses: PendingMessage[];
}

const initialState: ChatState = {
    chats: [],
    selectedChatId: null,
    isLoading: false,
    pendingResponses: [],
};

const chatSlice = createSlice({
    name: 'chat',
    initialState,
    reducers: {
        addChat: (state, action: PayloadAction<Chat>) => {
            state.chats.push(action.payload);
        },
        deleteChat: (state, action: PayloadAction<string>) => {
            state.chats = state.chats.filter(chat => chat.id !== action.payload);
            if (state.selectedChatId === action.payload) {
                state.selectedChatId = state.chats[0]?.id ?? null;
            }
        },
        updateChatTitle: (state, action: PayloadAction<{ chatId: string; title: string }>) => {
            const chat = state.chats.find(c => c.id === action.payload.chatId);
            if (chat) {
                chat.title = action.payload.title;
            }
        },
        selectChat: (state, action: PayloadAction<string>) => {
            state.selectedChatId = action.payload;
        },
        addMessage: (state, action: PayloadAction<{ chatId: string; message: Message }>) => {
            const chat = state.chats.find(c => c.id === action.payload.chatId);
            if (chat) {
                chat.messages.push(action.payload.message);
            }
        },
        addPendingResponse: (state, action: PayloadAction<PendingMessage>) => {
            if (!state.pendingResponses) {
                state.pendingResponses = [];
            }
            state.pendingResponses.push(action.payload);
        },
        removePendingResponse: (state, action: PayloadAction<string>) => {
            if (!state.pendingResponses) {
                state.pendingResponses = [];
                return;
            }
            
            const agentIndex = state.pendingResponses.findIndex(p => p.targetAgent === action.payload);
            if (agentIndex !== -1) {
                state.pendingResponses.splice(agentIndex, 1);
            }
        },
        clearAllPendingResponses: (state) => {
            state.pendingResponses = [];
        },
        setLoading: (state, action: PayloadAction<boolean>) => {
            state.isLoading = action.payload;
            if (!action.payload) {
                state.pendingResponses = [];
            }
        },
    },
});

export const { 
    addChat, 
    deleteChat, 
    updateChatTitle, 
    selectChat, 
    addMessage, 
    addPendingResponse,
    removePendingResponse,
    clearAllPendingResponses,
    setLoading 
} = chatSlice.actions;

export default chatSlice.reducer;
