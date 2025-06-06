import { createSlice, PayloadAction, createAsyncThunk } from '@reduxjs/toolkit';

// Based on healthcare_agents.yaml
const DEFAULT_AGENTS = [
    'Orchestrator',
    'PatientHistory',
    'Radiology',
    'PatientStatus',
    'ClinicalGuidelines',
    'ClinicalTrials',
    'ReportCreation'
];

// Thunk to fetch available agents from the API
export const fetchAvailableAgents = createAsyncThunk(
    'agent/fetchAvailableAgents',
    async (_, { rejectWithValue }) => {
        try {
            const response = await fetch('/api/agents');
            
            if (!response.ok) {
                throw new Error(`Error fetching agents: ${response.statusText}`);
            }
            
            const data = await response.json();
            return data.agents;
        } catch (error) {
            console.error('Failed to fetch available agents:', error);
            return rejectWithValue(error instanceof Error ? error.message : 'Unknown error');
        }
    }
);

interface AgentState {
    availableAgents: string[];
    loading: boolean;
    error: string | null;
}

const initialState: AgentState = {
    availableAgents: DEFAULT_AGENTS, // Will be replaced with API data when loaded
    loading: false,
    error: null
};

const agentSlice = createSlice({
    name: 'agent',
    initialState,
    reducers: {
        setAvailableAgents: (state, action: PayloadAction<string[]>) => {
            state.availableAgents = action.payload;
        },
        setLoading: (state, action: PayloadAction<boolean>) => {
            state.loading = action.payload;
        },
        setError: (state, action: PayloadAction<string | null>) => {
            state.error = action.payload;
        }
    },
    extraReducers: (builder) => {
        builder
            .addCase(fetchAvailableAgents.pending, (state) => {
                state.loading = true;
                state.error = null;
            })
            .addCase(fetchAvailableAgents.fulfilled, (state, action) => {
                state.loading = false;
                state.availableAgents = action.payload;
            })
            .addCase(fetchAvailableAgents.rejected, (state, action) => {
                state.loading = false;
                state.error = action.payload as string;
                // Fall back to default agents if the API call fails
                if (state.availableAgents.length === 0) {
                    state.availableAgents = DEFAULT_AGENTS;
                }
            });
    }
});

export const { setAvailableAgents, setLoading, setError } = agentSlice.actions;

export default agentSlice.reducer; 