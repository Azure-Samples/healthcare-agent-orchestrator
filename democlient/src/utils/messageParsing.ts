/**
 * Parse @mentions from a message and return an array of mentioned bot names
 * @param content The message content to parse
 * @param availableAgents List of available agent names
 * @returns Array of mentioned agent names
 */
export function parseMentions(content: string, availableAgents: string[]): string[] {
    const mentions: string[] = [];
    
    // Regular expression to match @mentions
    // This pattern matches @name that might be followed by a space or end of string
    const mentionRegex = /@(\w+)(?:\s|$)/g;
    let match;
    
    while ((match = mentionRegex.exec(content)) !== null) {
        const mentionedName = match[1];
        
        // Check if the mentioned name is a valid agent name (case insensitive)
        const agent = availableAgents.find(
            agent => agent.toLowerCase() === mentionedName.toLowerCase()
        );
        
        if (agent) {
            // Only add if it's not already in the mentions array
            if (!mentions.includes(agent)) {
                mentions.push(agent);
            }
        }
    }
    
    // Only return the first mention to ensure one mention per message
    return mentions.length > 0 ? [mentions[0]] : [];
}

/**
 * This function is no longer used with React Markdown but kept for reference
 * or in case we need to revert to HTML-based rendering
 * 
 * Highlight mentions in a message with blue color
 * @param content The message content to highlight
 * @returns HTML string with highlighted mentions
 */
export function highlightMentions(content: string): string {
    // Replace @mentions with styled spans
    return content.replace(/@(\w+)/g, '<span style="color:rgb(201, 204, 206); font-weight: bold;">@$1</span>');
}

/**
 * Get the target agent for a message
 * @param mentions Array of mentioned agent names
 * @returns The first mentioned agent or 'Orchestrator' as default
 */
export function getTargetAgent(mentions: string[]): string {
    // If there are mentions, use the first one, otherwise default to Orchestrator
    return mentions.length > 0 ? mentions[0] : 'Orchestrator';
} 