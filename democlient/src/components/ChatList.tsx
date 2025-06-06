import { useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
    Button,
    makeStyles,
    List,
    ListItem,
    tokens,
    Dialog,
    DialogTrigger,
    DialogSurface,
    DialogTitle,
    DialogBody,
    DialogActions,
    DialogContent,
    Input
} from '@fluentui/react-components';
import { 
    Add24Regular, 
    Delete24Regular, 
    Edit24Regular,
    Link24Regular,
    CheckmarkCircle24Regular,
    DismissCircle24Regular,
    Chat24Regular
} from '@fluentui/react-icons';
import { RootState } from '../store/store';
import { selectChat, addChat, deleteChat, updateChatTitle } from '../store/slices/chatSlice';
import { v4 as uuidv4 } from 'uuid';
import type { Chat } from '../types';

interface ChatListProps {
    onSelectChat?: () => void; // Callback when a chat is selected (for mobile)
}

const useStyles = makeStyles({
    container: {
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
    },
    header: {
        padding: '1rem',
        borderBottom: `1px solid ${tokens.colorNeutralStroke1}`,
    },
    list: {
        flex: 1,
        overflow: 'auto',
        padding: '0.5rem',
    },
    listItem: {
        cursor: 'pointer',
        padding: '0.75rem 1rem',
        margin: '0.25rem 0',
        borderRadius: '4px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        transition: 'background-color 0.2s ease-in-out, border-left 0.2s ease-in-out',
        '&:hover': {
            backgroundColor: tokens.colorNeutralBackground1Hover,
        },
        '&:hover .hoverActionButton': {
            opacity: 1,
        },
    },
    selectedItem: {
        backgroundColor: tokens.colorNeutralBackground2,
        borderLeft: `3px solid ${tokens.colorBrandBackground}`,
        '&:hover': {
            backgroundColor: tokens.colorNeutralBackground2Hover,
        },
    },
    chatTitle: {
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
    },
    chatIcon: {
        color: tokens.colorBrandForeground1,
    },
    hoverActionButton: {
        opacity: 0,
        transition: 'opacity 0.2s ease-in-out',
        minWidth: '32px',
        height: '32px',
        padding: '4px'
    },
    editActionButton: {
        minWidth: '32px',
        height: '32px',
        padding: '4px'
    },
    actionButtons: {
        display: 'flex',
        gap: '4px',
    },
    editInput: {
        flex: 1,
        marginRight: '8px',
    },
    dialogContent: {
        padding: '20px',
        maxWidth: '450px',
    },
    dialogActions: {
        paddingBottom: '20px',
        paddingRight: '20px',
    }
});

interface EditingState {
    chatId: string;
    title: string;
}

export default function ChatList({ onSelectChat }: ChatListProps) {
    const classes = useStyles();
    const dispatch = useDispatch();
    const chats = useSelector((state: RootState) => state.chat.chats);
    const selectedChatId = useSelector((state: RootState) => state.chat.selectedChatId);
    const [editing, setEditing] = useState<EditingState | null>(null);

    const handleNewChat = () => {
        // Create a new chat with a random ID
        const newId = uuidv4();
        const newChat: Chat = {
            id: newId,
            title: 'New Chat',
            messages: [],
            createdAt: new Date()
        };
        
        dispatch(addChat(newChat));
        dispatch(selectChat(newId));
        
        
        // Call onSelectChat if it exists (for mobile)
        if (onSelectChat) {
            onSelectChat();
        }
    };

    const handleSelectChat = (chatId: string) => {
        dispatch(selectChat(chatId));
        
        // Call onSelectChat if it exists (for mobile)
        if (onSelectChat) {
            onSelectChat();
        }
    };

    const handleDeleteChat = (chatId: string, e: React.MouseEvent) => {
        e.stopPropagation();
        const isCurrentlySelected = chatId === selectedChatId;
        console.log('isCurrentlySelected', isCurrentlySelected);
        
       
        dispatch(deleteChat(chatId));
    };

    const startEditing = (chat: Chat, e: React.MouseEvent) => {
        e.stopPropagation();
        setEditing({ chatId: chat.id, title: chat.title });
    };

    const cancelEditing = (e: React.MouseEvent) => {
        e.stopPropagation();
        setEditing(null);
    };

    const saveEditing = (e: React.MouseEvent) => {
        e.stopPropagation();
        if (editing) {
            dispatch(updateChatTitle({ chatId: editing.chatId, title: editing.title }));
            setEditing(null);
        }
    };

    return (
        <div className={classes.container}>
            <div className={classes.header}>
                <Button
                    icon={<Add24Regular />}
                    onClick={handleNewChat}
                >
                    New Chat
                </Button>
            </div>
            <List className={classes.list}>
                {chats.map(chat => (
                    <ListItem
                        key={chat.id}
                        className={`${classes.listItem} ${chat.id === selectedChatId ? classes.selectedItem : ''}`}
                        onClick={() => handleSelectChat(chat.id)}
                    >
                        {editing?.chatId === chat.id ? (
                            <>
                                <Input 
                                    className={classes.editInput}
                                    value={editing.title}
                                    onChange={(e, data) => setEditing({ ...editing, title: data.value })}
                                    onClick={(e) => e.stopPropagation()}
                                />
                                <div className={classes.actionButtons}>
                                    <Button
                                        className={classes.editActionButton}
                                        appearance="subtle"
                                        icon={<CheckmarkCircle24Regular />}
                                        onClick={saveEditing}
                                    />
                                    <Button
                                        className={classes.editActionButton}
                                        appearance="subtle"
                                        icon={<DismissCircle24Regular />}
                                        onClick={cancelEditing}
                                    />
                                </div>
                            </>
                        ) : (
                            <>
                                <div className={classes.chatTitle}>
                                    {chat.id === selectedChatId && (
                                        <Chat24Regular className={classes.chatIcon} />
                                    )}
                                    <span>{chat.title}</span>
                                </div>
                                <div className={classes.actionButtons}>
                                    <Button
                                        className={`hoverActionButton ${classes.hoverActionButton}`}
                                        appearance="subtle"
                                        icon={<Edit24Regular />}
                                        onClick={(e) => startEditing(chat, e)}
                                        title="Edit chat title"
                                    />
                                    <Dialog>
                                        <DialogTrigger disableButtonEnhancement>
                                            <Button
                                                className={`hoverActionButton ${classes.hoverActionButton}`}
                                                appearance="subtle"
                                                icon={<Delete24Regular />}
                                                onClick={(e) => e.stopPropagation()}
                                                title="Delete chat"
                                            />
                                        </DialogTrigger>
                                        <DialogSurface>
                                            <DialogBody>
                                                <DialogContent className={classes.dialogContent}>
                                                    <DialogTitle>Delete Chat</DialogTitle>
                                                    <p>Are you sure you want to delete this chat? This action cannot be undone.</p>
                                                </DialogContent>
                                                <DialogActions className={classes.dialogActions}>
                                                    <DialogTrigger disableButtonEnhancement>
                                                        <Button appearance="secondary">Cancel</Button>
                                                    </DialogTrigger>
                                                    <DialogTrigger disableButtonEnhancement>
                                                        <Button 
                                                            appearance="primary"
                                                            onClick={(e) => handleDeleteChat(chat.id, e)}
                                                        >
                                                            Delete
                                                        </Button>
                                                    </DialogTrigger>
                                                </DialogActions>
                                            </DialogBody>
                                        </DialogSurface>
                                    </Dialog>
                                </div>
                            </>
                        )}
                    </ListItem>
                ))}
            </List>
        </div>
    );
}
