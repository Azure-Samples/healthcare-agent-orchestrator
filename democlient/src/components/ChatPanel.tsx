import { useState, useRef, useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
    makeStyles,
    Input,
    Button,
    Text,
    tokens
} from '@fluentui/react-components';
import { Send24Regular } from '@fluentui/react-icons';
import { RootState } from '../store/store';
import { addMessage, setLoading, addPendingResponse, removePendingResponse } from '../store/slices/chatSlice';
import { api } from '../services/api';
import MessageList from './MessageList';
import MentionAutocomplete from './MentionAutocomplete';
import { parseMentions, getTargetAgent } from '../utils/messageParsing';
import { v4 as uuidv4 } from 'uuid';
import { useAuth } from '../contexts/AuthContext';

const useStyles = makeStyles({
    container: {
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        position: 'relative',
    },
    messageContainer: {
        flex: 1,
        overflow: 'auto',
        padding: '1rem',
        paddingBottom: '5rem', // Add padding to ensure messages don't get hidden behind the input
        '@media (max-width: 768px)': {
            paddingBottom: '9rem', // More padding on mobile
        }
    },
    inputContainer: {
        display: 'flex',
        flexDirection: 'column',
        padding: '1rem',
        borderTop: `1px solid ${tokens.colorNeutralStroke1}`,
        gap: '0.5rem',
        backgroundColor: tokens.colorNeutralBackground1,
        position: 'absolute',
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 10,
        '@media (max-width: 768px)': {
            padding: '0.75rem',
            paddingBottom: '6.0rem',
            bottom: 'env(safe-area-inset-bottom, 0px)', // Use safe area insets if available
        }
    },
    deleteButton: {
        opacity: 0,
        transition: 'opacity 0.2s ease-in-out',
        cursor: 'pointer',
        padding: '2px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        '&:hover': {
            backgroundColor: tokens.colorNeutralBackground4,
            borderRadius: '50%',
        },
    },
    inputRow: {
        display: 'flex',
        gap: '0.5rem',
    },
    input: {
        flex: 1,
    },
    hiddenInput: {
        display: 'none',
    },
    // Mobile send button style for compact UI
    sendButton: {
        '@media (max-width: 768px)': {
            padding: '0 10px',
            minWidth: '40px',
        }
    },
    sendButtonText: {
        '@media (max-width: 768px)': {
            display: 'none'
        }
    }
});

export default function ChatPanel() {
    const classes = useStyles();
    const dispatch = useDispatch();
    const [message, setMessage] = useState('');
    const messageContainerRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);
    const selectedChatId = useSelector((state: RootState) => state.chat.selectedChatId);
    const selectedChat = useSelector((state: RootState) => 
        state.chat.chats.find(chat => chat.id === selectedChatId)
    );
    const isLoading = useSelector((state: RootState) => state.chat.isLoading);
    const pendingResponses = useSelector((state: RootState) => state.chat.pendingResponses);
    const user = useSelector((state: RootState) => state.auth.user);
    const availableAgents = useSelector((state: RootState) => state.agent.availableAgents);
    
    // Autocomplete state
    const [showAutocomplete, setShowAutocomplete] = useState(false);
    const [autocompletePosition, setAutocompletePosition] = useState({ top: 0, left: 0 });
    const [mentionQuery, setMentionQuery] = useState('');
    const [hasMention, setHasMention] = useState(false);

    // Clear loading state and all pending responses on initial mount
    useEffect(() => {
        dispatch(setLoading(false));
        dispatch({ type: 'chat/clearAllPendingResponses' });
    }, [dispatch]);

    // Initialize pendingResponses if needed
    useEffect(() => {
        if (pendingResponses === undefined) {
            dispatch({ type: 'chat/clearAllPendingResponses' });
        }
    }, [dispatch, pendingResponses]);

    // Scroll to bottom when messages change or when selected chat changes
    useEffect(() => {
        scrollToBottom();
    }, [selectedChat?.messages, selectedChatId]);
    
    
    // Log for debugging
    useEffect(() => {
        console.log('Current pending responses:', pendingResponses);
    }, [pendingResponses]);

    // Add useEffect to handle viewport adjustments for mobile keyboard and browser UI
    useEffect(() => {
        // Function to adjust for viewport on mobile
        const adjustViewportForMobile = () => {
            // Use visual viewport API if available
            if (window.visualViewport) {
                const viewport = window.visualViewport;
                
                const viewportHandler = () => {
                    const inputContainer = document.querySelector(`.${classes.inputContainer}`);
                    if (inputContainer && inputContainer instanceof HTMLElement) {
                        // Calculate offset from bottom based on viewport height vs window height
                        const bottomOffset = window.innerHeight - viewport.height - viewport.offsetTop;
                        
                        // Set the bottom position to account for keyboard and browser UI
                        if (bottomOffset > 0) {
                            // When keyboard is open, move up by the bottomOffset
                            inputContainer.style.bottom = `${bottomOffset}px`;
                            
                            // Ensure scrolling to bottom works with the new position
                            setTimeout(scrollToBottom, 100);
                        } else {
                            // Reset when keyboard is closed
                            inputContainer.style.bottom = 'env(safe-area-inset-bottom, 0px)';
                        }
                    }
                };
                
                // Add event listener for viewport changes
                viewport.addEventListener('resize', viewportHandler);
                viewport.addEventListener('scroll', viewportHandler);
                
                // Initial adjustment
                viewportHandler();
                
                return () => {
                    viewport.removeEventListener('resize', viewportHandler);
                    viewport.removeEventListener('scroll', viewportHandler);
                };
            }
            
            // Fallback for browsers without visualViewport API
            const handleResize = () => {
                // Try to account for browser UI by comparing window.innerHeight to screen.height
                const browserUiHeight = Math.max(0, screen.height - window.innerHeight);
                document.documentElement.style.setProperty('--browser-ui-height', `${browserUiHeight}px`);
                
                // Scroll to bottom after resize
                scrollToBottom();
            };
            
            window.addEventListener('resize', handleResize);
            handleResize();
            
            return () => window.removeEventListener('resize', handleResize);
        };
        
        // Run the adjustment function
        const cleanup = adjustViewportForMobile();
        return cleanup;
    }, []);

    const scrollToBottom = () => {
        if (messageContainerRef.current) {
            messageContainerRef.current.scrollTop = messageContainerRef.current.scrollHeight;
        }
    };

    const getUsernameFromEmail = (email: string | undefined) => {
        return email ? email.split('@')[0] : 'user';
    };

    // Helper function to get cursor position
    const getCursorPosition = (input: HTMLInputElement): { left: number } | null => {
        // Create a temporary element to measure text width
        const computedStyle = window.getComputedStyle(input);
        const div = document.createElement('div');
        div.style.position = 'absolute';
        div.style.visibility = 'hidden';
        div.style.whiteSpace = 'pre';
        div.style.font = computedStyle.font;
        div.style.letterSpacing = computedStyle.letterSpacing;
        div.style.fontFamily = computedStyle.fontFamily;
        div.style.fontSize = computedStyle.fontSize;
        div.style.fontWeight = computedStyle.fontWeight;
        
        document.body.appendChild(div);
        
        // Get cursor position
        const cursorPosition = input.selectionStart || 0;
        const textBeforeCursor = input.value.substring(0, cursorPosition);
        
        // Measure text width
        div.textContent = textBeforeCursor;
        const textWidth = div.clientWidth;
        
        // Clean up
        document.body.removeChild(div);
        
        return { left: textWidth };
    };

    // Handle text input changes and detect @ mentions
    const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>, data: { value: string }) => {
        const newValue = data.value;
        setMessage(newValue);
        
        // Check for @ symbol to trigger autocomplete
        if (!hasMention) { // Only allow one mention per message
            const atIndex = newValue.lastIndexOf('@');
            if (atIndex !== -1) {
                const lastSpaceIndex = newValue.lastIndexOf(' ', atIndex);
                const isAtStartOrAfterSpace = atIndex === 0 || lastSpaceIndex === atIndex - 1;
                
                if (isAtStartOrAfterSpace) {
                    // Extract the query text after @
                    const query = newValue.substring(atIndex + 1);
                    setMentionQuery(query);
                    
                    // Calculate position for autocomplete popup
                    if (inputRef.current) {
                        const inputRect = inputRef.current.getBoundingClientRect();
                        const caretPosition = getCursorPosition(inputRef.current);
                        
                        setAutocompletePosition({
                            top: inputRect.top, // Use the top of the input field
                            left: caretPosition ? inputRect.left + caretPosition.left : inputRect.left + 10
                        });
                        
                        setShowAutocomplete(true);
                    }
                }
            } else {
                setShowAutocomplete(false);
            }
        } else {
            // If there's already a mention, check if it was removed
            if (!newValue.includes('@')) {
                setHasMention(false);
            }
        }
    };
    
    // Handle selection from autocomplete menu
    const handleMentionSelect = (agent: string) => {
        if (hasMention) return; // Prevent multiple mentions
        
        const atIndex = message.lastIndexOf('@');
        if (atIndex !== -1) {
            // Replace the @query with @agent
            const newMessage = message.substring(0, atIndex) + `@${agent} `;
            setMessage(newMessage);
            setHasMention(true);
            setShowAutocomplete(false);
            
            // Focus back on input and move cursor to end
            if (inputRef.current) {
                inputRef.current.focus();
                inputRef.current.selectionStart = newMessage.length;
                inputRef.current.selectionEnd = newMessage.length;
            }
        }
    };
    
    // Close autocomplete menu
    const handleAutocompleteClose = () => {
        setShowAutocomplete(false);
    };

    const handleSend = async () => {
        console.log('handleSend called', selectedChatId, message, user);
        if (!selectedChatId || (!message.trim()) || !user) return;

        console.log('handleSend called');
        // Parse mentions from the message
        const mentions = parseMentions(message, availableAgents);
        
        // Determine target agent - first mention or default to Orchestrator
        const targetAgent = getTargetAgent(mentions);

        // Create user message object
        const userMessage = {
            id: uuidv4(),
            content: message,
            sender: getUsernameFromEmail(user.email),
            timestamp: new Date(),
            isBot: false,
            mentions: mentions.length > 0 ? [...mentions] : undefined
        };

        // Add user message to chat immediately
        dispatch(addMessage({ 
            chatId: selectedChatId, 
            message: userMessage
        }));

        // Clear input fields
        setMessage('');
        
        // Set loading state to true to show loading indicator
        dispatch(setLoading(true));
        
        // Add pending response for the target agent
        dispatch(addPendingResponse({
            targetAgent,
            timestamp: new Date()
        }));

        // Debug logging
        console.log('Sending message to API:', {
            chatId: selectedChatId,
            content: message,
            sender: getUsernameFromEmail(user.email),
            mentions: mentions.length > 0 ? [...mentions] : undefined
        });

        try {
            // Use WebSocket for message communication
            await api.sendMessage(
                selectedChatId, 
                {
                    content: message,
                    sender: getUsernameFromEmail(user.email),
                    mentions: mentions.length > 0 ? [...mentions] : undefined
                },
                // This callback is called for each message received
                (botMessage) => {
                    // Add each bot message to the chat as it arrives
                    dispatch(addMessage({
                        chatId: selectedChatId,
                        message: botMessage
                    }));
                    
                    // Remove pending response once we get first message
                    if (pendingResponses && pendingResponses.length > 0) {
                        dispatch(removePendingResponse(targetAgent));
                    }
                }
            );
            
            // Set loading to false when all messages are received
            dispatch(setLoading(false));
            
        } catch (error) {
            console.error('Error sending message:', error);
            
            // Remove pending response for this agent
            dispatch(removePendingResponse(targetAgent));
            
            // Set loading to false
            dispatch(setLoading(false));
            
            // Add error message if API call fails
            dispatch(addMessage({
                chatId: selectedChatId,
                message: {
                    id: uuidv4(),
                    content: "Sorry, there was an error processing your message. Please try again.",
                    sender: "System",
                    timestamp: new Date(),
                    isBot: true,
                }
            }));
        }
        
        // Reset mention state
        setHasMention(false);
    };

    if (!selectedChat) {
        return <div style={{ color: tokens.colorNeutralForeground1, margin: '1rem' }}><Text>Select a chat to start messaging</Text></div>;
    }

    return (
        <div className={classes.container}>
            <div className={classes.messageContainer} ref={messageContainerRef}>
                <MessageList messages={selectedChat.messages} />
            </div>
            <div className={classes.inputContainer}>
                
                <div className={classes.inputRow}>
                    <Input
                        className={classes.input}
                        value={message} 
                        onChange={handleInputChange}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !showAutocomplete) {
                                handleSend();
                            }
                        }}
                        ref={inputRef}
                        placeholder="Type a message... (Use @ to mention an agent)"
                    />
                    <Button
                        className={classes.sendButton}
                        icon={<Send24Regular />}
                        onClick={handleSend}
                    >
                        <span className={classes.sendButtonText}>Send</span>
                    </Button>
                </div>
                
                {/* Mention autocomplete dropdown */}
                <MentionAutocomplete
                    agents={availableAgents}
                    textAreaRef={inputRef}
                    isOpen={showAutocomplete}
                    onSelect={handleMentionSelect}
                    onClose={handleAutocompleteClose}
                    position={autocompletePosition}
                    query={mentionQuery}
                />
            </div>
        </div>
    );
}
