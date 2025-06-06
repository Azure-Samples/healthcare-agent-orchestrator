import { configureStore } from '@reduxjs/toolkit';
import authReducer from '@store/slices/authSlice';
import chatReducer from '@store/slices/chatSlice';
import agentReducer from '@store/slices/agentSlice';
import { loadState, saveState } from '../utils/storage';
import debounce from 'lodash/debounce';

// Load state from localStorage
const preloadedState = loadState();

export const store = configureStore({
    reducer: {
        auth: authReducer,
        chat: chatReducer,
        agent: agentReducer,
    },
    preloadedState,
    middleware: (getDefaultMiddleware) =>
        getDefaultMiddleware({
            serializableCheck: {
                // Ignore these action types
                ignoredActions: ['chat/addMessage', 'chat/addChat', 'chat/addPendingResponse'],
                // Ignore these field paths in the state
                ignoredPaths: ['chat.chats', 'chat.pendingResponses'],
            },
        }),
});

// Save state to localStorage
store.subscribe(
    // Debounce to prevent too frequent saves
    debounce(() => {
        const state = store.getState();
        saveState({
            chat: state.chat, // Only save chat state, not auth state
        });
    }, 1000)
);

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
