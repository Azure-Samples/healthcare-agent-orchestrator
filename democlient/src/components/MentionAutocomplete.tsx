import React, { useState, useEffect, useRef } from 'react';
import { 
    makeStyles, 
    Menu, 
    MenuItem, 
    tokens,
    Portal
} from '@fluentui/react-components';

const useStyles = makeStyles({
    menuContainer: {
        position: 'absolute',
        zIndex: 100,
        width: '200px',
        boxShadow: tokens.shadow16,
        borderRadius: tokens.borderRadiusMedium,
        backgroundColor: tokens.colorNeutralBackground1,
        border: `1px solid ${tokens.colorNeutralStroke1}`,
        overflow: 'hidden',
        maxHeight: '200px',
        overflowY: 'auto',
    },
    menuItem: {
        padding: '8px 12px',
        cursor: 'pointer',
        '&:hover': {
            backgroundColor: tokens.colorNeutralBackground2,
        },
    },
    selectedItem: {
        backgroundColor: tokens.colorBrandBackground,
        color: tokens.colorNeutralForegroundOnBrand,
        '&:hover': {
            backgroundColor: tokens.colorBrandBackgroundHover,
        }
    }
});

interface MentionAutocompleteProps {
    agents: string[];
    textAreaRef: React.RefObject<HTMLInputElement | HTMLTextAreaElement>;
    isOpen: boolean;
    onSelect: (agent: string) => void;
    onClose: () => void;
    position: { top: number; left: number };
    query: string;
}

const MentionAutocomplete: React.FC<MentionAutocompleteProps> = ({
    agents,
    isOpen,
    onSelect,
    onClose,
    position,
    query
}) => {
    const styles = useStyles();
    const menuRef = useRef<HTMLDivElement>(null);
    const [selectedIndex, setSelectedIndex] = useState(0);
    const [filteredAgents, setFilteredAgents] = useState<string[]>(agents);
    const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });

    // Calculate position - show dropdown ABOVE the cursor position
    useEffect(() => {
        // Calculate menu height based on number of items (up to 5)
        const itemHeight = 36; // Approximate height of each menu item
        const numItems = Math.min(filteredAgents.length, 5);
        const menuHeight = numItems * itemHeight;
        
        // Position menu above the input field so its bottom edge aligns with the text field
        setMenuPosition({
            top: position.top - menuHeight, // Place above the input field
            left: position.left
        });
    }, [position, filteredAgents.length]);

    // Filter agents based on query
    useEffect(() => {
        if (query) {
            const filtered = agents.filter(agent => 
                agent.toLowerCase().includes(query.toLowerCase())
            );
            setFilteredAgents(filtered);
            // Reset selection to first item
            setSelectedIndex(0);
        } else {
            setFilteredAgents(agents);
        }
    }, [agents, query]);

    // Handle click outside to close the menu
    useEffect(() => {
        if (!isOpen) return;
        
        const handleClickOutside = (event: MouseEvent) => {
            if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
                onClose();
            }
        };
        
        document.addEventListener('mousedown', handleClickOutside);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, [isOpen, onClose]);

    // Handle keyboard navigation
    useEffect(() => {
        if (!isOpen) return;
        
        const handleKeyDown = (e: KeyboardEvent) => {
            switch (e.key) {
                case 'ArrowDown':
                    e.preventDefault();
                    setSelectedIndex(prev => (prev + 1) % filteredAgents.length);
                    break;
                case 'ArrowUp':
                    e.preventDefault();
                    setSelectedIndex(prev => (prev - 1 + filteredAgents.length) % filteredAgents.length);
                    break;
                case 'Enter':
                    e.preventDefault();
                    if (filteredAgents.length > 0) {
                        onSelect(filteredAgents[selectedIndex]);
                    }
                    break;
                case 'Escape':
                    e.preventDefault();
                    onClose();
                    break;
                default:
                    break;
            }
        };
        
        document.addEventListener('keydown', handleKeyDown);
        return () => {
            document.removeEventListener('keydown', handleKeyDown);
        };
    }, [isOpen, selectedIndex, filteredAgents, onSelect, onClose]);

    if (!isOpen || filteredAgents.length === 0) {
        return null;
    }

    return (
        <Portal>
            <div 
                ref={menuRef}
                className={styles.menuContainer}
                style={{ 
                    top: menuPosition.top,
                    left: menuPosition.left
                }}
            >
                {filteredAgents.map((agent, index) => (
                    <div
                        key={agent}
                        className={`${styles.menuItem} ${index === selectedIndex ? styles.selectedItem : ''}`}
                        onClick={() => onSelect(agent)}
                    >
                        {agent}
                    </div>
                ))}
            </div>
        </Portal>
    );
};

export default MentionAutocomplete; 