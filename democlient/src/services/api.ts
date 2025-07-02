import type { Chat, Message, SendMessageResponse, SendMessagesResponse } from '../types';

// Base URL for API requests
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';
// Base URL for WebSocket connections (replace http/https with ws/wss)
export const WS_BASE_URL = API_BASE_URL.replace(/^http/, 'ws').replace(/^https/, 'wss');

// Utility function to check if WebSockets are supported in the browser
export const isWebSocketSupported = (): boolean => {
    return typeof WebSocket !== 'undefined';
};

interface SendMessageRequest {
    content: string;
    sender: string;
    mentions?: string[];
}

// Helper function to make authenticated API requests
export const apiRequest = async (
  endpoint: string,
  method: string = 'GET',
  data?: any
): Promise<any> => {
  const url = `${API_BASE_URL}${endpoint}`;
  
  const options: RequestInit = {
    method,
    credentials: 'include', // This includes cookies in the request
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
  };

  if (data) {
    options.body = JSON.stringify(data);
  }

  try {
    const response = await fetch(url, options);
    
    // Handle unauthorized errors
    if (response.status === 401) {
      // For App Service Auth, this will trigger a redirect to the login page
      window.location.href = '/.auth/login/aad';
      throw new Error('Unauthorized');
    }
    
    // Handle not found and other errors
    if (!response.ok) {
      throw new Error(`API request failed: ${response.statusText}`);
    }
    
    // Parse the response as JSON
    return await response.json();
  } catch (error) {
    console.error('API request error:', error);
    throw error;
  }
};

// Legacy API support using the old approach with auth token
const getAuthHeaders = async (): Promise<Record<string, string>> => {
    const headers: Record<string, string> = {
        'Content-Type': 'application/json'
    };
    
    try {
    } catch (error) {
        console.log('Could not get auth token', error);
    }
    
    return headers;
};

// API for chat functionality
interface ChatAPI {
    sendWebSocketMessage(chatId: string, messageData: SendMessageRequest, onMessageCallback: (message: Message) => void): Promise<void>;
    sendMessage(chatId: string, messageData: SendMessageRequest, onMessageCallback: (message: Message) => void): Promise<void>;
}

export const api: ChatAPI = {
    async sendWebSocketMessage(chatId: string, messageData: SendMessageRequest, onMessageCallback: (message: Message) => void): Promise<void> {
        console.log('API sendWebSocketMessage called with:', { chatId, messageData });
        let messagesReceived = 0;
        let ws: WebSocket | null = null;
        
        return new Promise((resolve, reject) => {
            try {
                // Create WebSocket connection
                ws = new WebSocket(`${WS_BASE_URL}/ws/chats/${chatId}/messages`);
                
                // Handle connection open
                ws.onopen = () => {
                    console.log('WebSocket connection established');
                    // Send the message data once connected
                    if (ws) {
                        ws.send(JSON.stringify(messageData));
                    }
                };
                
                // Handle incoming messages
                ws.onmessage = (event) => {
                    console.log('WebSocket message received:', event.data);
                    try {
                        const data = JSON.parse(event.data);
                        
                        // Check for done signal
                        if (data.type === 'done') {
                            console.log('WebSocket stream complete');
                            ws?.close();
                            resolve();
                            return;
                        }
                        
                        // Check for error messages
                        if (data.error) {
                            console.error('WebSocket error:', data.error);
                            reject(new Error(data.error));
                            ws?.close();
                            return;
                        }
                        
                        // Process actual message
                        const message: Message = {
                            ...data,
                            timestamp: new Date(data.timestamp),
                            isBot: data.isBot === true // Ensure isBot is a boolean
                        };
                        
                        // Call the callback with the message
                        onMessageCallback(message);
                        messagesReceived++;
                        console.log(`WebSocket message #${messagesReceived} sent to callback`);
                    } catch (e) {
                        console.error('Error parsing WebSocket message:', e);
                    }
                };
                
                // Handle errors
                ws.onerror = (error) => {
                    console.error('WebSocket error:', error);
                    reject(error);
                };
                
                // Handle connection close
                ws.onclose = () => {
                    console.log('WebSocket connection closed');
                    
                    // If no messages were received, create a fallback
                    if (messagesReceived === 0) {
                        console.warn('No messages received from WebSocket, creating fallback');
                        const fallbackMessage: Message = {
                            id: 'fallback-' + Date.now(),
                            content: "No response was received. Please try again.",
                            sender: "System",
                            timestamp: new Date(),
                            isBot: true
                        };
                        onMessageCallback(fallbackMessage);
                    }
                    
                    // Resolve the promise if it hasn't been already
                    resolve();
                };
                
                
                
            } catch (error) {
                console.error('Error setting up WebSocket:', error);
                reject(error);
            }
        });
    },
    
    async sendMessage(chatId: string, messageData: SendMessageRequest, onMessageCallback: (message: Message) => void): Promise<void> {
        if (!isWebSocketSupported()) {
            console.error('WebSockets are not supported in this browser');
            const errorMessage: Message = {
                id: 'error-' + Date.now(),
                content: "Your browser doesn't support WebSockets, which are required for this application.",
                sender: "System",
                timestamp: new Date(),
                isBot: true
            };
            onMessageCallback(errorMessage);
            return;
        }

        try {
            // Use WebSocket for communication
            await this.sendWebSocketMessage(chatId, messageData, onMessageCallback);
        } catch (error) {
            console.error('WebSocket communication failed:', error);
            const fallbackMessage: Message = {
                id: 'fallback-' + Date.now(),
                content: "Communication with the server failed. Please try again later.",
                sender: "System",
                timestamp: new Date(),
                isBot: true
            };
            onMessageCallback(fallbackMessage);
        }
    }
};

