const STORAGE_KEY = 'biomed_chat_state';

export const saveState = (state: any) => {
    try {
        const serializedState = JSON.stringify(state);
        localStorage.setItem(STORAGE_KEY, serializedState);
    } catch (err) {
        console.error('Could not save state:', err);
    }
};

export const loadState = () => {
    try {
        const serializedState = localStorage.getItem(STORAGE_KEY);
        if (!serializedState) return undefined;
        
        const state = JSON.parse(serializedState);
        
        // Convert stored date strings back to Date objects
        if (state.chat?.chats) {
            state.chat.chats = state.chat.chats.map((chat: any) => ({
                ...chat,
                createdAt: new Date(chat.createdAt),
                messages: chat.messages.map((msg: any) => ({
                    ...msg,
                    timestamp: new Date(msg.timestamp)
                }))
            }));
        }
        
        return state;
    } catch (err) {
        console.error('Could not load state:', err);
        return undefined;
    }
}; 