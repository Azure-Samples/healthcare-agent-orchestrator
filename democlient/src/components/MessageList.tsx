import React from 'react';
import { makeStyles, Text, tokens, mergeClasses } from '@fluentui/react-components';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useSelector } from 'react-redux';
import type { Message } from '../types';
import { RootState } from '../store/store';

// Add global animations via style tag
const AnimationStyles = () => (
  <style>
    {`
    @keyframes pulseDot1 {
      0% { opacity: 0.3; transform: translateY(0px); }
      50% { opacity: 1; transform: translateY(-1px); }
      100% { opacity: 0.3; transform: translateY(0px); }
    }
    
    @keyframes pulseDot2 {
      0% { opacity: 0.3; transform: translateY(0px); }
      50% { opacity: 1; transform: translateY(-1px); }
      100% { opacity: 0.3; transform: translateY(0px); }
    }
    
    @keyframes pulseDot3 {
      0% { opacity: 0.3; transform: translateY(0px); }
      50% { opacity: 1; transform: translateY(-1px); }
      100% { opacity: 0.3; transform: translateY(0px); }
    }
    
    .dot1, .dot2, .dot3 {
      display: inline-block;
      width: 2px;
      height: 2px;
      border-radius: 50%;
      background-color: #333;
      margin: 0 2px;
    }
    
    .dot1 {
      animation: pulseDot1 1.4s infinite ease-in-out;
    }
    
    .dot2 {
      animation: pulseDot2 1.4s infinite ease-in-out 0.2s;
    }
    
    .dot3 {
      animation: pulseDot3 1.4s infinite ease-in-out 0.4s;
    }
    `}
  </style>
);

// Define keyframes for dot animations using CSS animation names
const useStyles = makeStyles({
    container: {
        display: 'flex',
        flexDirection: 'column',
        gap: '1rem',
        padding: '1rem',
    },
    messageGroupLeft: {
        display: 'flex',
        flexDirection: 'column',
        maxWidth: '90%',
        alignSelf: 'flex-start',
    },
    loadingDot:{
        display: 'flex',
        flexDirection: 'column',
        maxWidth: '90%',
        alignSelf: 'flex-start',
        content: '""',
        width: '110px',
        height: '50px'
    },
    messageGroupRight: {
        display: 'flex',
        flexDirection: 'column',
        maxWidth: '90%',
        alignSelf: 'flex-end',
    },
    sender: {
        fontSize: tokens.fontSizeBase200,
        color: tokens.colorNeutralForeground3,
        marginBottom: '4px',
        paddingLeft: '0.5rem',
    },
    message: {
        padding: '0.75rem 1rem',
        borderRadius: '12px',
        width: 'fit-content',
        maxWidth: '100%',
        wordWrap: 'break-word',
    },
    userMessage: {
        backgroundColor: tokens.colorBrandBackground,
        color: tokens.colorNeutralForegroundInverted,
        borderTopRightRadius: '4px',
    },
    botMessage: {
        backgroundColor: tokens.colorNeutralBackground4,
        color: tokens.colorNeutralForeground1,
        borderTopLeftRadius: '4px',
    },
    loadingMessage: {
        borderRadius: '12px',
        width: 'fit-content',
        maxWidth: '100%',
        wordWrap: 'break-word',
        backgroundColor: tokens.colorNeutralBackground4,
        height: '80%',
        padding: '0.5rem 0.75rem', // Slightly smaller padding
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
    },
    loadingDots: {
        display: 'flex',
        alignItems: 'center',
        gap: '2px',
    },
    // Animation classes are added via className instead of makeStyles keyframes
    markdownContainer: {
        '& p': {
            margin: '0 0 0.75rem 0',
            '&:last-child': {
                marginBottom: 0,
            }
        },
        '& h1, & h2, & h3, & h4, & h5, & h6': {
            marginTop: '0.5rem',
            marginBottom: '0.5rem',
        },
        '& ul, & ol': {
            paddingLeft: '1.5rem',
            marginBottom: '0.75rem',
        },
        '& code': {
            backgroundColor: 'rgba(0, 0, 0, 0.1)',
            padding: '0.1rem 0.2rem',
            borderRadius: '3px',
            fontFamily: 'monospace',
        },
        '& pre': {
            backgroundColor: 'rgba(0, 0, 0, 0.1)',
            padding: '0.5rem',
            borderRadius: '4px',
            overflowX: 'auto',
            '& code': {
                backgroundColor: 'transparent',
                padding: 0,
            }
        },
        '& blockquote': {
            marginLeft: '0.5rem',
            paddingLeft: '0.5rem',
            borderLeft: '4px solid rgba(0, 0, 0, 0.2)',
            color: 'rgba(0, 0, 0, 0.7)',
        },
        '& a': {
            color: 'inherit',
            textDecoration: 'underline',
        },
        '& table': {
            borderCollapse: 'collapse',
            width: '100%',
            margin: '0.75rem 0',
            '& th, & td': {
                border: '1px solid rgba(0, 0, 0, 0.2)',
                padding: '0.3rem 0.5rem',
                textAlign: 'left',
            },
            '& th': {
                backgroundColor: 'rgba(0, 0, 0, 0.1)',
            },
        },
    },
    userMarkdownContainer: {
        '& blockquote': {
            borderLeftColor: 'rgba(255, 255, 255, 0.4)',
            color: 'rgba(255, 255, 255, 0.8)',
        },
        '& code, & pre': {
            backgroundColor: 'rgba(255, 255, 255, 0.2)',
        },
        '& a': {
            color: 'inherit',
        },
        '& table th, & table td': {
            border: '1px solid rgba(255, 255, 255, 0.3)',
        },
        '& table th': {
            backgroundColor: 'rgba(255, 255, 255, 0.2)',
        },
    },
});

// Loading dots component
const LoadingDots = () => {
    const styles = useStyles();
    
    return (
        <div className={styles.loadingDots}>
            <span className="dot1"></span>
            <span className="dot2"></span>
            <span className="dot3"></span>
        </div>
    );
};

interface MessageListProps {
    messages: Message[];
}

export default function MessageList({ messages }: MessageListProps) {
    const styles = useStyles();
    const isLoading = useSelector((state: RootState) => state.chat.isLoading);
    const pendingResponses = useSelector((state: RootState) => state.chat.pendingResponses);
    const selectedChatId = useSelector((state: RootState) => state.chat.selectedChatId);
    const availableAgents = useSelector((state: RootState) => state.agent.availableAgents);
    
    // Process message content to handle special formatting
    const renderMessageContent = (content: string, isBot: boolean) => {
        // Ensure content is a string
        if (!content || typeof content !== 'string') return '';
        
        // Use ReactMarkdown to render markdown content
        return (
            <div className={mergeClasses(
                styles.markdownContainer,
                !isBot ? styles.userMarkdownContainer : undefined
            )}>
                <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                        // Custom renderer for links to open in new tab
                        a: ({ node, ...props }) => (
                            <a 
                                {...props} 
                                target="_blank" 
                                rel="noopener noreferrer"
                            />
                        )
                    }}
                >
                    {content}
                </ReactMarkdown>
            </div>
        );
    };
    
    return (
        <div className={styles.container}>
            {/* Add the animation styles */}
            <AnimationStyles />
            
            {/* Render all regular messages */}
            {messages && messages.map(message => {
                // Skip invalid messages
                if (!message || typeof message !== 'object') return null;
                
                // Check if isBot is defined, default to false if not
                const isBot = message.isBot === true;
                
                return (
                    <div 
                        key={message.id || `msg-${Math.random()}`} 
                        className={isBot ? styles.messageGroupLeft : styles.messageGroupRight}
                    >
                        <Text className={styles.sender}>
                            {message.sender || ''}
                        </Text>
                        <div
                            className={mergeClasses(
                                styles.message,
                                isBot ? styles.botMessage : styles.userMessage
                            )}
                        >
                            {renderMessageContent(message.content || '', isBot)}
                        </div>
                    </div>
                );
            })}
            
            {/* Render loading indicators for each pending response */}
            {isLoading === true && pendingResponses && Array.isArray(pendingResponses) && pendingResponses.length > 0 && 
                pendingResponses.map((pendingResponse, index) => {
                    if (!pendingResponse) return null;
                    return (
                        <div key={`loading-${index}`} className={styles.loadingDot}>
                            <Text className={styles.sender}>
                                {pendingResponse.targetAgent || 'Agent'}
                            </Text>
                            <div className={styles.loadingMessage}>
                                <LoadingDots />
                            </div>
                        </div>
                    );
                })
            }
            
            {/* Fallback loading indicator if pendingResponses is empty but isLoading is true */}
            {isLoading === true && (!pendingResponses || !Array.isArray(pendingResponses) || pendingResponses.length === 0) && (
                <div className={styles.loadingDot}>
                    <Text className={styles.sender}>
                        Orchestrator
                    </Text>
                    <div className={styles.loadingMessage}>
                        <LoadingDots />
                    </div>
                </div>
            )}
        </div>
    );
}
