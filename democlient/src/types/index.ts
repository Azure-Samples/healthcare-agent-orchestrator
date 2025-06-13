export interface Message {
    id: string;
    content: string;
    sender: string;
    timestamp: Date;
    isBot: boolean;
    attachments?: string[]; // Array of file names
    mentions?: string[]; // Array of mentioned bot names
}

export interface SendMessageResponse {
    message: Message;
    error: string | null;
}

export interface SendMessagesResponse {
    messages: Message[];
    error: string | null;
}

export interface Chat {
    id: string;
    title: string;
    messages: Message[];
    createdAt: Date;
}

// This type can be removed if you're fully migrating to UserInfo from backendAuthService
// But we'll keep it for backward compatibility
export interface User {
    id?: string;
    name?: string;
    email: string;
    accessToken?: string;
    roles?: string[];
}
