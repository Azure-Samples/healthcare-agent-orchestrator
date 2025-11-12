# Healthcare Agent Orchestrator - Technical Workshop Guide
**Duration:** 20-30 minutes  
**Audience:** Technical stakeholders  
**Last Updated:** January 2025

---

## Validation of Understanding

### ✅ **Your understanding is largely correct!** Here are some key validations and clarifications:

**What You Got Right:**
1. **Generalizability**: The HAO is indeed a generalizable orchestration framework. Any AI system, API, or data source can be exposed as an agent with the proper interface.
2. **Code Focus**: For a 20-30 minute session, focusing on the orchestrator mechanics and agent definitions (agents.yaml) is the right approach.
3. **Data Flexibility**: The orchestrator doesn't dictate data sources - agents handle their own data connections through their tools/plugins.
4. **FHIR Integration**: The HAO demonstrates healthcare interoperability through FHIR, but this is just one example of data connectivity.

**Important Clarifications:**
1. **Workflow is Synchronous**: The orchestrator uses a turn-based conversation model. Agents are invoked sequentially based on the selection strategy. Each agent completes its work before control returns to the orchestrator, which then decides the next agent. There's no async/parallel agent execution in the current implementation.

2. **LLM Requirement**: Not all agents require their own LLM! 
   - Standard agents (ChatCompletionAgent) use LLMs to reason and decide when to call their tools
   - However, agents can be "thin wrappers" - the [`HealthcareAgent`](../src/healthcare_agents/agent.py) class shows this: it can delegate to external agent services without its own LLM
   - Tools/plugins themselves don't need LLMs - they're just functions (e.g., FHIR query, image analysis API)

3. **Interface Requirements**: The "proper interface" is:
   - For standard agents: defined in `agents.yaml` + optional tools that expose a `create_plugin()` factory function
   - For custom agents: must implement Semantic Kernel's `Agent` interface (see `HealthcareAgent` class)
   - Implementation is in the HAO repo - the framework loads and orchestrates them

---

## Workshop Structure (30 minutes)

### **Guiding Principle**
Focus on insights **not obvious from reading the documentation** - the "how it works" and "why it matters" that only become clear through deep technical understanding and real-world application.

---

### **Part 1: Welcome & Agenda Setting (2-3 min)**
**Objective:** Establish audience expectations and prioritize content dynamically

**Flow:**
1. Welcome and brief self-introduction
2. Present the planned agenda (keep it visible):
   - Solution Architecture & Use Case Example
   - Agents: Data & Model Connections
   - Orchestrator Deep Dive
   - Additional Use Cases & Q&A
3. **Key Question:** "What would you like to focus on most today? Which topics matter most to your work?"
4. Note responses and adjust time allocation on the fly

**Why this works:** Technical audiences appreciate having input on focus areas. This ensures you spend the most time on what they actually need.

---

### **Part 2: Use Case Showcase - Tumor Board Preparation (4-5 min)**
**Objective:** Establish value and relevance upfront (the "wow factor")

**Topics to cover:**
- **Real-world impact:** Stanford partnership and tumor board workflow
- **The challenge:** 2-4 hours of manual preparation across multiple systems and specialties
- **HAO's solution:** Automated multi-agent workflow that:
  - Aggregates patient timeline from EHR (via FHIR)
  - Analyzes radiology images (CXRReportGen model)
  - Searches clinical trials (ClinicalTrials.gov API)
  - Reviews research literature (GraphRAG)
  - Generates comprehensive report (Word document)
- **Key insight:** "This isn't one AI agent—it's multiple specialized agents coordinated by an orchestrator"

**Transition:** "Let me show you the architecture that makes this possible."

---

### **Part 3: Solution Architecture Overview (4-5 min)**
**Objective:** Provide mental model before diving into technical details

**Architecture diagram walkthrough:**
1. **Show the full diagram** (Clinical researcher → Teams → Agent Bots → Backend → Data/Models)
2. **Highlight key aspects:**
   - **Modular architecture:** Agents defined in YAML, orchestrated by central engine
   - **Data agnostic:** Connect to any data source (EHR via FHIR, Fabric, Blob Storage)
   - **Model agnostic:** Connect to any AI model or external API
   - **Interface flexibility:** Teams, custom UI, not necessarily chat-based

3. **Three pillars framework:**
   - **Orchestrator:** The coordination engine (selection + termination strategies)
   - **Agents:** Specialized AI capabilities (each agent = model + tools + instructions)
   - **Data:** Abstracted access layer (FHIR, Fabric, APIs, databases)

**Key message:** "HAO is a tool that supports the implementation and execution of multi-agent applications. Think tumor board prep, prior authorization, administrative workflows, quality analysis."

**Transition:** "Let's see what these agents actually look like, closing the loop on our tumor board example."

---

### **Part 4: Agent Examples & Composition (5-6 min)**
**Objective:** Show how agents are built and connected to data/models

**Key architectural insight first:** "HAO is a central backend that governs agent connections. Everything runs inside it—agent code, tools, data access, LLM connections—except for custom agents deployed as separate microservices."

---

**4.1 The Garden Path: From Configuration to Running Agents (2 min)**

**Visual flow to show:**
```
agents.yaml
  ↓ [load at startup]
create_app_context() → stores agent configs
  ↓ [user sends message]
group_chat.create_group_chat() → orchestration begins
  ↓ [for each agent]
_create_agent() → tool loading + agent instantiation
  ↓
CustomChatCompletionAgent (95% of cases)
OR
HealthcareAgent (microservice wrapper, 5%)
```

**Explain the timing:**
- **Startup:** `create_app_context()` loads `agents.yaml`, stores configs in memory
- **Per message:** `create_group_chat()` creates fresh agent instances for that conversation
- **Per agent:** `_create_agent()` dynamically imports tools, configures LLM, instantiates agent

**Show the code locations:**
```python
# app.py - Startup
def create_app_context():
    agent_config = load_agent_config(scenario)  # Reads agents.yaml
    return AppContext(all_agent_configs=agent_config)

# group_chat.py - Per message
def create_group_chat(app_ctx, chat_ctx):
    agents = [_create_agent(cfg) for cfg in app_ctx.all_agent_configs]
    return AgentGroupChat(agents=agents, ...)

# group_chat.py - Per agent
def _create_agent(agent_config):
    # Import tools dynamically
    tool_module = importlib.import_module(f"scenarios.{scenario}.tools.{tool_name}")
    plugin = tool_module.create_plugin(plugin_config)
    
    # Create agent
    return CustomChatCompletionAgent(kernel=kernel, name=..., instructions=...)
```

---

**4.2 UI Connection Points: Single Backend, Multiple Interfaces (1 min)**

**HAO supports multiple UIs—all hitting the same backend:**

| Interface | Entry Point | Protocol | Use Case |
|-----------|------------|----------|----------|
| **Teams** | `/api/messages/{agent_name}` | HTTP POST (Bot Framework) | Enterprise deployment |
| **Custom Web UI** | `/api/ws/chats/{chat_id}` | WebSocket | Demo/development |
| **MCP Clients** | `/mcp/orchestrator` | HTTP (MCP protocol) | Copilot Studio integration |

**Show the routing:**
```python
# app.py - Adapter setup for Teams
adapters = {
    "Orchestrator": CloudAdapter(...),  # Bot Framework adapter
    "PatientHistory": CloudAdapter(...),
    # One adapter per agent for Teams integration
}

# routes/api/messages.py - Teams routing (one endpoint per agent)
@router.post("/api/messages/{agent_name}")
async def messages(agent_name: str):
    adapter = adapters[agent_name]
    bot = bots[agent_name]
    await adapter.process_activity(request, bot)

# routes/api/chats.py - Custom UI routing (single endpoint, mentions in message)
@router.websocket("/api/ws/chats/{chat_id}")
async def websocket_chat_endpoint(chat_id: str):
    mentions = client_message.get("mentions", [])  # @Orchestrator
    chat, chat_ctx = group_chat.create_group_chat(app_ctx, chat_ctx)
    # Same orchestration, different entry point
```

**Key insight:** "Same agents, same orchestration, different UI—Teams for production, WebSocket for demos, MCP for Copilot."

---

**4.3 Agent Examples from Tumor Board (1 min)**
- **PatientHistory:** Connects to FHIR, retrieves clinical notes, generates timeline
- **Radiology:** Connects to Azure ML model (CXRReportGen), analyzes chest x-rays
- **MedicalResearch:** Connects to GraphRAG API, searches research literature
- **ClinicalTrials:** Connects to ClinicalTrials.gov REST API

**Key insight:** "Different data sources, different models, same orchestration framework."

---

**4.4 agents.yaml Deep Dive (1 min)**
**Show `agents.yaml` snippet** (PatientHistory example):
```yaml
- name: PatientHistory
  instructions: |
    You are an AI agent tasked with loading and presenting patient data.
    1. Request Patient ID if not provided
    2. Load data using `load_patient_data` tool
    3. Create timeline using `create_timeline` tool
    4. Yield back to *Orchestrator*
  tools:
    - name: patient_data
  description: |
    A patient history agent. **You provide**: timeline. **You need**: patient ID.
  temperature: 0
```

**Highlight:** "This YAML becomes a `CustomChatCompletionAgent` with tools automatically loaded. Add an agent? Edit this file, deploy. That's it."

---

**4.5 Two Agent Types (30 sec)**
1. **Standard agents (95%):** `CustomChatCompletionAgent` - defined in YAML, run in HAO
2. **External agents (5%):** `HealthcareAgent` - wrapper for microservices, marked with `healthcare_agent: true`

**Why external agents exist:** "For scalability, isolation, or integrating legacy services deployed separately. Most customers never need this."

---

**Prepared deep-dives (if audience asks):**
- FHIR integration: OAuth, DocumentReference queries, data transformation
- Fabric integration: Lakehouse queries via REST API
- Model examples: NLP interface over image segmentation (tumor highlighting)
- `healthcare_agents.yaml`: Alternative config for deploying agents as separate services

**Transition:** "Now let's see how the orchestrator coordinates all these agents."

---

### **Part 5: Orchestrator Deep Dive (8-10 min)**
**Objective:** Demystify the coordination mechanism—this is the "secret sauce"

**Key message first:** "The orchestrator is just another agent—but with a special role: facilitation."

**Topics to cover:**

**5.1 Core Orchestration Mechanism (3-4 min)**
- **File:** `/src/group_chat.py` - `create_group_chat()` function
- **Show code structure:**
  ```python
  chat = AgentGroupChat(
      agents=agents,
      selection_strategy=KernelFunctionSelectionStrategy(...),
      termination_strategy=KernelFunctionTerminationStrategy(...)
  )
  ```

**5.2 Key Components (2-3 min)**
1. **Selection Strategy** (who speaks next?)
   - LLM-based decision using conversation history
   - Rules: facilitator always starts, agents hand off via "*AgentName*" syntax
   - Show prompt snippet: "Determine which participant takes the next turn..."

2. **Termination Strategy** (when to end?)
   - Only facilitator decides to stop
   - Checks if question is for user vs. another agent
   - Maximum iterations: 30 turns

3. **Agent Creation Loop**
   - Dynamically loads tools from `scenarios/{scenario}/tools/`
   - Supports function tools (Python plugins) and OpenAPI tools
   - Injects configuration via `PluginConfiguration`

**5.3 Important Settings (1-2 min)**
| Setting | Purpose | Default |
|---------|---------|---------|
| `facilitator` | Designates moderator agent | From agents.yaml |
| `temperature` | Model randomness per agent | 0 (deterministic) |
| `maximum_iterations` | Max conversation turns | 30 |
| `function_choice_behavior` | Auto tool calling | Enabled |

**5.4 Workflow: Synchronous Execution (1-2 min)**
**Critical clarification:**
- **Turn-based, not parallel:** Agents execute sequentially
- Workflow: User message → Selection → Agent execution → Termination check → Repeat
- **No async/background agents:** Each agent completes before next begins

**Why this matters:** Predictable, debuggable, easier to reason about conversation flow.

**Transition:** "Let's look at other ways this pattern is being applied."

---

### **Part 6: Additional Use Cases & Q&A (5-7 min)**
**Objective:** Expand the art of the possible, invite discussion

**Additional use cases (1 slide each, detail as time permits):**
1. **Clinical Research:** Cohort analysis across Fabric lakehouse + visualization
2. **Prior Authorization:** Document gathering + policy matching + form generation
3. **Administrative Workflows:** Scheduling optimization, worklist prioritization
4. **Quality & Safety Analysis:** Incident review, pattern detection, reporting
5. **Patient Education:** Medical jargon translation, glossary building

**Key message:** "The same orchestration pattern—different agents, different data sources, different workflows."

**Open Q&A:**
- Invite questions on any topic
- Have prepared answers for common questions (see Q&A section below)
- Share this document afterward for reference

---

## Agents and Orchestration Deep Dive

### How Multiple Agents Are Governed

The orchestrator uses **Semantic Kernel's AgentGroupChat** with custom selection and termination strategies to manage multi-agent conversations.

#### **Main Orchestrator Code**
**File:** `/src/group_chat.py`

```python
def create_group_chat(
    app_ctx: AppContext, chat_ctx: ChatContext, participants: list[dict] = None
) -> Tuple[AgentGroupChat, ChatContext]:
    """
    Creates an agent group chat with selection and termination strategies.
    
    Args:
        app_ctx: Application context with agent configs and services
        chat_ctx: Chat context with history and session data
        participants: Optional list of agent configs (defaults to all agents)
    
    Returns:
        Tuple of (AgentGroupChat, ChatContext)
    """
    participant_configs = participants or app_ctx.all_agent_configs
    
    # Create agents from configuration
    agents = [_create_agent(agent) for agent in all_agents_config]
    
    # Define selection strategy (who speaks next?)
    chat = AgentGroupChat(
        agents=agents,
        chat_history=chat_ctx.chat_history,
        selection_strategy=KernelFunctionSelectionStrategy(
            function=selection_function,  # LLM-based decision
            kernel=_create_kernel_with_chat_completion(),
            result_parser=evaluate_selection,
            agent_variable_name="agents",
            history_variable_name="history",
        ),
        termination_strategy=KernelFunctionTerminationStrategy(
            agents=[facilitator],  # Only facilitator decides when to end
            function=termination_function,
            kernel=_create_kernel_with_chat_completion(),
            result_parser=evaluate_termination,
            maximum_iterations=30,
        ),
    )
    
    return (chat, chat_ctx)
```

**Key Components:**

1. **Selection Strategy** - Determines which agent speaks next:
```python
selection_prompt_config = PromptTemplateConfig(
    name="selection",
    template=f"""
    You are overseeing a group chat between several AI agents and a human user.
    Determine which participant takes the next turn based on:
    
    1. **Participants**: {list of agent names}
    2. **Rules**:
        - {facilitator} Always Starts
        - Agents may request other agents by name
        - "back to you *agent_name*" syntax for handoffs
        - Once per turn per agent
        - Default to {facilitator}
    
    History: {{{{$history}}}}
    """
)
```

2. **Termination Strategy** - Decides when conversation should end:
```python
termination_prompt_config = PromptTemplateConfig(
    name="termination",
    template=f"""
    Determine if the conversation should end based on the most recent message.
    
    Return "yes" if:
    - Question is addressed to the user
    - Question is addressed to "we" or "us"
    
    Return "no" if:
    - Question/command is addressed to another agent
    
    History: {{{{$history}}}}
    """
)
```

3. **Agent Creation** - Each agent is instantiated with its configuration:
```python
def _create_agent(agent_config: dict):
    agent_kernel = _create_kernel_with_chat_completion()
    
    # Create plugin configuration for tools
    plugin_config = PluginConfiguration(
        kernel=agent_kernel,
        agent_config=agent_config,
        data_access=app_ctx.data_access,
        chat_ctx=chat_ctx,
        azureml_token_provider=app_ctx.azureml_token_provider,
        app_ctx=app_ctx,
    )
    
    # Load agent tools/plugins
    for tool in agent_config.get("tools", []):
        tool_name = tool.get("name")
        tool_type = tool.get("type", DEFAULT_TOOL_TYPE)
        
        if tool_type == "function":
            # Dynamic import of tool module
            tool_module = importlib.import_module(f"scenarios.{scenario}.tools.{tool_name}")
            agent_kernel.add_plugin(
                tool_module.create_plugin(plugin_config), 
                plugin_name=tool_name
            )
        elif tool_type == "openapi":
            # Load OpenAPI specification as tools
            agent_kernel.add_plugin_from_openapi(
                plugin_name=tool_name,
                openapi_document_path=tool.get("openapi_document_path"),
                execution_settings=OpenAPIFunctionExecutionParameters(...)
            )
    
    # Return appropriate agent type
    return CustomChatCompletionAgent(
        kernel=agent_kernel,
        name=agent_config["name"],
        instructions=agent_config["instructions"],
        description=agent_config["description"],
        arguments=arguments
    )
```

### Important Orchestrator Settings

**File:** `/src/group_chat.py`

| Setting | Purpose | Location |
|---------|---------|----------|
| `maximum_iterations` | Max conversation turns before forced termination | Line ~312 |
| `temperature` | Model randomness (per-agent configurable) | Line ~180-188 |
| `function_choice_behavior` | Controls when agents call their tools | Line ~184 |
| `seed=42` | Ensures reproducible outputs | Line ~184 |
| `facilitator` | Designates which agent moderates | Derived from `agents.yaml` |

### Workflow: Synchronous Turn-Based Execution

**Important:** The orchestrator operates **synchronously** in a turn-based manner:

1. User sends a message
2. Orchestrator invokes **selection strategy** → determines next agent
3. Selected agent executes:
   - Reasons about the task
   - Calls its tools/plugins as needed (function calling)
   - Returns response
4. Orchestrator invokes **termination strategy** → continue or end?
5. If continue, go to step 2
6. If end, return control to user

**No async/parallel execution:** Agents cannot be "triggered" to run in background. Each must complete before the next begins.

### How Agents Are Defined

**File:** `/src/scenarios/default/config/agents.yaml`

```yaml
- name: Orchestrator                    # Required: Unique identifier
  facilitator: true                     # Optional: Marks this as moderator (only 1)
  instructions: |                       # Required: System prompt / instructions
    You are an AI agent facilitating a discussion between experts...
    {{aiAgents}}                        # Dynamic placeholder for agent list
  description: |                        # Required: Used by orchestrator for routing
    Your role is to moderate the discussion, present order of participants...
  temperature: 0                        # Optional: Model temperature (default: 0)
  tools:                                # Optional: List of tools this agent can use
    - name: patient_data                # Function tool (Python plugin)
      type: function                    # Default type
    - name: time_api                    # OpenAPI tool
      type: openapi
      openapi_document_path: scenarios/default/config/openapi/time_api.yaml
      server_url_override: https://api.example.com
  
- name: PatientHistory
  instructions: |
    You are an AI agent tasked with loading and presenting patient data...
    1. Request Patient ID if not provided
    2. Load all relevant patient data using `load_patient_data` tool
    3. Create timeline using `create_timeline`
    4. Present data without alterations
    5. Yield back to *Orchestrator* by saying "back to you: *Orchestrator*"
  tools:
    - name: patient_data
  description: |
    A patient history agent. **You provide**: patient timeline and patient 
    information. **You need** a patient ID from the user.

- name: Radiology
  instructions: |
    You are an AI agent for analyzing chest x-rays using CXRReportGen model.
    Always use the generate_findings tool...
  tools:
    - name: cxr_report_gen
  description: |
    A radiologist agent. **You provide**: radiology insights from chest x-rays. 
    **You need**: images from PatientHistory.
```

**Key Fields:**
- **name**: Unique identifier used throughout the system
- **instructions**: The system prompt the LLM receives (can reference other agents, include handoff protocols)
- **description**: Used by orchestrator's selection strategy to route requests
- **facilitator**: Boolean flag - designates the moderating agent
- **tools**: List of plugins/tools (function or openapi type)
- **temperature**: LLM temperature (0 = deterministic, higher = more random)

---

## Interface Expected for Agents

### agents.yaml to Agent Instances: The Complete Flow

**Understanding how configuration becomes running agents:**

**1. Application Startup** (`app.py`):
```python
def create_app_context():
    # Load scenario from environment (e.g., "default")
    scenario = os.getenv("SCENARIO")
    
    # Load and parse agents.yaml
    agent_config = load_agent_config(scenario)  
    # Returns: [{"name": "Orchestrator", "instructions": "...", ...}, ...]
    
    return AppContext(
        all_agent_configs=agent_config,  # Stored for later use
        ...
    )
```

**2. Conversation Starts** - User sends message via Teams/API:
```python
# In message handler
chat_ctx = await data_access.chat_context_accessor.read(conversation_id)
(chat, chat_ctx) = create_group_chat(app_ctx, chat_ctx)  # NOW agents are created
```

**3. Agent Creation** (`group_chat.py` - `create_group_chat()`):
```python
def create_group_chat(app_ctx: AppContext, chat_ctx: ChatContext):
    # Get agent configs from AppContext
    all_agents_config = app_ctx.all_agent_configs
    
    # Create agent instance for each config
    agents = [_create_agent(agent_config) for agent_config in all_agents_config]
    
    # agents = [OrchestratorAgent, PatientHistoryAgent, RadiologyAgent, ...]
    
    return AgentGroupChat(agents=agents, ...)
```

**4. Individual Agent Creation** (`_create_agent()` function):
```python
def _create_agent(agent_config: dict):
    # agent_config = {"name": "PatientHistory", "instructions": "...", "tools": [...]}
    
    # Check agent type
    is_healthcare_agent = "healthcare_agent" in agent_config
    
    if not is_healthcare_agent:
        # STANDARD AGENT PATH (most common)
        
        # Create kernel with Azure OpenAI connection
        agent_kernel = _create_kernel_with_chat_completion()
        
        # Load tools dynamically
        for tool in agent_config.get("tools", []):
            tool_name = tool["name"]  # e.g., "patient_data"
            
            # Dynamic import: scenarios/default/tools/patient_data.py
            tool_module = importlib.import_module(f"scenarios.{scenario}.tools.{tool_name}")
            
            # Call create_plugin() factory function
            plugin = tool_module.create_plugin(plugin_config)
            
            # Attach to agent's kernel
            agent_kernel.add_plugin(plugin, plugin_name=tool_name)
        
        # Create agent instance
        return CustomChatCompletionAgent(
            kernel=agent_kernel,                    # LLM + tools
            name=agent_config["name"],
            instructions=agent_config["instructions"],  # System prompt
            description=agent_config["description"],
            arguments=arguments
        )
    else:
        # EXTERNAL AGENT PATH (rare)
        return HealthcareAgent(
            name=agent_config["name"],
            chat_ctx=chat_ctx,
            app_ctx=app_ctx
        )
```

**Flow Summary:**
```
agents.yaml 
  ↓ [load_agent_config @ startup]
list[dict] in AppContext
  ↓ [user sends message]
create_group_chat() called
  ↓ [for each agent config]
_create_agent()
  ├─ Create Kernel with LLM
  ├─ Import tools (importlib)
  ├─ Call create_plugin() for each tool
  └─ Instantiate CustomChatCompletionAgent OR HealthcareAgent
  ↓
list[Agent] ready for orchestration
  ↓
AgentGroupChat.invoke() - conversation begins
```

**Azure Bots vs Agent Instances:**
- **Azure Bot Services:** Infrastructure created at deployment (Bicep), handles Teams integration
- **Agent Instances:** Created at runtime per conversation, handles AI reasoning
- **Connection:** Bot receives message → routes to message handler → creates agent instances → orchestration happens

**Complete flow:**
```python
# 1. Teams → Azure Bot Service → HAO backend
POST /api/messages/Orchestrator
  ↓
# 2. CloudAdapter receives and processes Bot Framework activity
adapter = adapters["Orchestrator"]
bot = bots["Orchestrator"]  # AssistantBot instance
await adapter.process_activity(request, bot)
  ↓
# 3. AssistantBot.on_turn() handles the message
class AssistantBot(ActivityHandler):
    async def on_message_activity(self, turn_context: TurnContext):
        # Get message content
        message = turn_context.activity.text
        
        # Create group chat with ALL agents
        chat, chat_ctx = group_chat.create_group_chat(app_ctx, chat_ctx)
        
        # chat.agents = [
        #   CustomChatCompletionAgent("Orchestrator"),
        #   CustomChatCompletionAgent("PatientHistory"),
        #   CustomChatCompletionAgent("Radiology"),
        #   HealthcareAgent("ExternalAgent"),  # IF healthcare_agent: true in yaml
        #   ...
        # ]
        
        # Invoke orchestration
        async for response in chat.invoke():
            await turn_context.send_activity(response.content)
```

**Layer Responsibilities:**
```
CloudAdapter (Transport Layer)
  ├─ Handles Bot Framework protocol
  ├─ Authenticates with Azure Bot Service
  ├─ Parses Teams messages
  └─ NOT an agent, just receives/sends messages

AssistantBot (Message Handler Layer)
  ├─ Receives processed message from CloudAdapter
  ├─ Loads chat context
  ├─ Creates AgentGroupChat
  └─ Invokes orchestration

AgentGroupChat (Orchestration Layer)
  ├─ Contains list of agents:
  │   ├─ CustomChatCompletionAgent (standard agents)
  │   └─ HealthcareAgent (external service delegates)
  ├─ Selection strategy
  └─ Termination strategy
```

---

### Standard Agent Interface (Most Common)

**Agent Type:** `CustomChatCompletionAgent` (inherits from Semantic Kernel's `ChatCompletionAgent`)

**What's needed:** Entry in `agents.yaml` with required fields

**Where implemented:** HAO automatically creates agent instances in `_create_agent()` function

**Example:**
```yaml
- name: MyNewAgent
  instructions: |
    You are an expert in X. Use your tools to accomplish Y.
    When done, say "back to you: *Orchestrator*"
  description: |
    An expert in X. **You provide**: Y. **You need**: Z.
  tools:
    - name: my_tool_plugin
```

**Do you need an LLM?** Yes - `CustomChatCompletionAgent` uses Azure OpenAI to reason about when/how to call its tools.

**How it's created:**
```python
# In group_chat.py - _create_agent()
return CustomChatCompletionAgent(
    kernel=agent_kernel,           # Contains LLM connection
    name=agent_config["name"],
    instructions=agent_config["instructions"],  # System prompt
    description=agent_config["description"],
    arguments=arguments
)
```

**This covers:** PatientHistory, Radiology, ClinicalTrials, ClinicalGuidelines, MedicalResearch, ReportCreation - essentially all typical agents.

### Tool/Plugin Interface

**What's needed:** Python module with `create_plugin()` factory function

**Where implemented:** In the HAO repo at `src/scenarios/{scenario}/tools/{tool_name}.py`

**Example:**
```python
# File: src/scenarios/default/tools/my_custom_tool.py

from semantic_kernel.functions import kernel_function
from data_models.plugin_configuration import PluginConfiguration

def create_plugin(plugin_config: PluginConfiguration):
    """Factory function - HAO automatically discovers and calls this"""
    return MyCustomToolPlugin(plugin_config)

class MyCustomToolPlugin:
    def __init__(self, config: PluginConfiguration):
        self.config = config
        self.data_access = config.data_access
        self.kernel = config.kernel
        self.chat_ctx = config.chat_ctx
    
    @kernel_function(
        description="Performs X operation with Y input"
    )
    async def do_something(self, parameter: str) -> str:
        """
        This function will be discoverable by the agent's LLM.
        The LLM decides when to call it based on the description.
        """
        # Access data sources
        data = await self.config.data_access.clinical_note_accessor.read_all(parameter)
        
        # Perform operation
        result = process_data(data)
        
        return result
```

**Do you need an LLM?** No - tools are just Python functions. The agent's LLM decides when to call them.

### External Agent Interface (Advanced/Rare)

**Agent Type:** `HealthcareAgent` (custom class that delegates to external service)

**What's needed:** 
1. Python class implementing Semantic Kernel's `Agent` interface (already implemented in HAO)
2. External agent service deployed separately (with its own LLM)
3. Entry in `agents.yaml` with special flag

**Where implemented:** Pre-built in HAO repo at `src/healthcare_agents/agent.py`

**Purpose:** Integrate existing agent services that use Azure Bot Framework's Direct Line API

**How it works:**
```
HAO Orchestrator
  ↓ (message routing)
HealthcareAgent (thin wrapper in HAO)
  ↓ (Direct Line WebSocket/HTTP)
External Healthcare Agent Service (separate deployment)
  ↓ (has its own LLM, tools, reasoning)
Returns response
```

**Configuration in agents.yaml:**
```yaml
- name: MyExternalAgent
  healthcare_agent: true              # Special flag triggers HealthcareAgent creation
  instructions: |
    Instructions are sent to the external service...
  description: |
    External agent. **You provide**: X. **You need**: Y.
```

**Key implementation detail:**
```python
# File: src/healthcare_agents/agent.py

class HealthcareAgent(Agent):
    """Delegates to external Healthcare Agent Service via Direct Line"""
    
    def __init__(self, name: str, chat_ctx: ChatContext, app_ctx: AppContext):
        super().__init__(name=name)
        self._client = HealthcareAgentServiceClient(
            url=config.directline_url,        # Direct Line endpoint
            directline_secret_key=secret_key,  # Auth for external service
        )
    
    async def get_attachments(self) -> list[dict]:
        """Prepare context (e.g., x-ray images) for external service"""
        attachments = []
        for data in self._chat_ctx.patient_data:
            if data['type'] in ['x-ray image']:
                blob_sas_url = await self._data_access.blob_sas_delegate.get_blob_sas_url(data['url'])
                attachments.append({
                    'contentType': "image/png",
                    'contentUrl': blob_sas_url  # External service downloads image
                })
        return attachments
```

**Do you need an LLM in HAO?** No - HAO just routes messages. The external service has its own LLM.

**When to use:**
- ✅ Integrating legacy agent services you can't migrate
- ✅ Microservice separation for scaling/isolation
- ✅ Third-party agent services using Bot Framework
- ❌ **NOT for typical agent development** - use standard agents instead

**Communication Protocol:** Azure Bot Framework Direct Line API (WebSocket or HTTP polling) - not Teams, this is bot-to-bot communication.

### Summary: Three Types of Agents

| Type | Needs LLM in HAO? | Implementation | Use Case |
|------|-------------------|----------------|----------|
| **Standard Agent** (`CustomChatCompletionAgent`) | ✅ Yes | `agents.yaml` + optional tools | Most agents - LLM reasoning with tools |
| **Tool/Plugin** | ❌ No | `tools/{name}.py` with `create_plugin()` | Functions called by agents |
| **External Agent** (`HealthcareAgent`) | ❌ No* | `agents.yaml` with `healthcare_agent: true` | Delegate to external agent service |

\* External service has its own LLM - abstracted from HAO

**Key Insight:** The orchestrator is flexible - it orchestrates conversations between ANY agents that implement the Agent interface, whether they're LLM-based locally, rule-based, or external services.

**When to use each:**
- **Standard Agent:** 95% of use cases - define in YAML, add tools as needed
- **Tool/Plugin:** Always - agents need tools to access data/models
- **External Agent:** Only when integrating existing agent services or requiring microservice separation

---

## Part 3: Data & Model Connections

### Data Access Layer Architecture

The HAO uses an abstraction layer that decouples data sources from agent logic, making it easy to swap data sources without changing agent code.

**File:** `/src/data_models/data_access.py`

```python
@dataclass(frozen=True)
class DataAccess:
    """Composite object containing all data accessors"""
    blob_sas_delegate: BlobSasDelegate
    chat_artifact_accessor: ChatArtifactAccessor      # Agent-generated data
    chat_context_accessor: ChatContextAccessor        # Session state
    clinical_note_accessor: ClinicalNoteAccessor      # Patient notes (pluggable!)
    image_accessor: ImageAccessor                     # Medical images

def create_data_access(
    blob_service_client: BlobServiceClient,
    credential: AsyncTokenCredential
) -> DataAccess:
    """Factory function - switches data sources based on env variable"""
    
    clinical_notes_source = os.getenv("CLINICAL_NOTES_SOURCE")
    
    if clinical_notes_source == "fhir":
        clinical_note_accessor = FhirClinicalNoteAccessor.from_credential(
            fhir_url=os.getenv("FHIR_SERVICE_ENDPOINT"),
            credential=credential,
        )
    elif clinical_notes_source == "fabric":
        clinical_note_accessor = FabricClinicalNoteAccessor.from_credential(
            fabric_user_data_function_endpoint=os.getenv("FABRIC_USER_DATA_FUNCTION_ENDPOINT"),
            credential=credential,
        )
    else:
        # Default: Azure Blob Storage
        clinical_note_accessor = ClinicalNoteAccessor(blob_service_client)
    
    return DataAccess(
        clinical_note_accessor=clinical_note_accessor,
        image_accessor=ImageAccessor(blob_service_client),
        chat_artifact_accessor=ChatArtifactAccessor(blob_service_client),
        chat_context_accessor=ChatContextAccessor(blob_service_client),
        blob_sas_delegate=BlobSasDelegate(blob_service_client),
    )
```

### Data Sources: Three Implementations, One Interface

#### 1. **Azure Blob Storage** (Default)
**File:** `/src/data_models/clinical_note_accessor.py`

```python
class ClinicalNoteAccessor:
    """Reads clinical notes from Azure Blob Storage"""
    
    def __init__(self, blob_service_client: BlobServiceClient):
        self.container_client = blob_service_client.get_container_client("patient-data")
    
    async def read_all(self, patient_id: str) -> list[str]:
        """Fetch all clinical notes for a patient"""
        blob_names = [
            name async for name in self.container_client.list_blob_names(
                name_starts_with=f"{patient_id}/clinical_notes/"
            )
        ]
        return [await self._read_blob(name) for name in blob_names]
```

**Data Structure:**
```
patient-data/
  patient_4/
    clinical_notes/
      note_001.json    # {"id": "001", "date": "2023-01-15", "type": "progress note", "text": "..."}
      note_002.json
    images/
      xray_001.png
      metadata.json    # [{"filename": "xray_001.png", "type": "chest x-ray"}]
```

#### 2. **FHIR Service**
**File:** `/src/data_models/fhir/fhir_clinical_note_accessor.py`

```python
class FhirClinicalNoteAccessor:
    """Reads clinical notes from FHIR server via DocumentReference resources"""
    
    @staticmethod
    def from_credential(fhir_url: str, credential: AsyncTokenCredential):
        """Factory: Authenticate with Azure Managed Identity"""
        token_provider = get_bearer_token_provider(
            credential, 
            "https://azurehealthcareapis.com/.default"
        )
        return FhirClinicalNoteAccessor(fhir_url, token_provider)
    
    async def read_all(self, patient_id: str) -> list[str]:
        """Query FHIR server for patient's DocumentReference resources"""
        url = f"{self.fhir_url}/DocumentReference"
        params = {"patient": patient_id}
        
        async with aiohttp.ClientSession() as session:
            # Get OAuth token
            token = await self.token_provider()
            headers = {"Authorization": f"Bearer {token}"}
            
            # Query FHIR server
            async with session.get(url, params=params, headers=headers) as resp:
                bundle = await resp.json()
                
                # Extract clinical notes from DocumentReference.content
                return [
                    self._extract_note_text(doc_ref) 
                    for doc_ref in bundle.get("entry", [])
                ]
```

**Key Features:**
- OAuth2 authentication (Managed Identity or Client Secret)
- Queries `Patient` and `DocumentReference` FHIR resources
- Converts FHIR data to HAO's clinical note format
- See `docs/fhir_integration.md` for full details

#### 3. **Microsoft Fabric**
**File:** `/src/data_models/fabric/fabric_clinical_note_accessor.py`

Similar pattern - queries Fabric lakehouse via REST API.

### How Agents Connect to Data

**Agents don't directly access data sources.** They use tools that leverage the `DataAccess` abstraction:

```python
# File: src/scenarios/default/tools/patient_data.py

class PatientDataPlugin:
    def __init__(self, kernel: Kernel, chat_ctx: ChatContext, data_access: DataAccess):
        self.data_access = data_access  # Injected by framework
    
    @kernel_function(
        description="Load patient images and reports from data store"
    )
    async def load_patient_data(self, patient_id: str) -> str:
        # Use abstracted accessor - doesn't know if it's Blob/FHIR/Fabric!
        clinical_notes = await self.data_access.clinical_note_accessor.read_all(patient_id)
        images = await self.data_access.image_accessor.get_metadata_list(patient_id)
        
        return format_patient_data(clinical_notes, images)
```

### Model Connections: Examples of Different Agent Types

#### Example 1: LLM-Based Agent with Tools
**MedicalResearch agent** → GraphRAG API

```yaml
# agents.yaml
- name: MedicalResearch
  instructions: |
    You answer research questions using Microsoft GraphRAG tool.
    Always cite sources exactly as provided...
  graph_rag_url: "https://ncsls.azure-api.net/"
  graph_rag_index_name: "nsclc-index-360MB"
  tools:
    - name: graph_rag
```

```python
# src/scenarios/default/tools/graph_rag.py
class GraphRagPlugin:
    def __init__(self, graph_rag_url: str, subscription_key: str, index_name: str):
        self.url = graph_rag_url
        self.key = subscription_key
        self.index = index_name
    
    @kernel_function()
    async def search_research(self, query: str) -> str:
        """Search GraphRAG index for research papers"""
        async with aiohttp.ClientSession() as session:
            headers = {"Ocp-Apim-Subscription-Key": self.key}
            async with session.post(
                f"{self.url}/search",
                json={"query": query, "index_name": self.index},
                headers=headers
            ) as resp:
                return await resp.json()
```

#### Example 2: Azure ML Hosted Model
**Radiology agent** → CXRReportGen model (Azure ML endpoint)

```python
# src/scenarios/default/tools/cxr_report_gen.py
class CxrReportGenPlugin:
    def __init__(self, endpoint_url: str, token_provider: Callable):
        self.endpoint = endpoint_url
        self.get_token = token_provider
    
    @kernel_function()
    async def generate_findings(self, patient_id: str, filename: str, indication: str) -> str:
        """Generate radiology report from chest x-ray using Azure ML model"""
        
        # Get image from data access
        image_bytes = await self.data_access.image_accessor.read(patient_id, filename)
        base64_image = base64.b64encode(image_bytes.read()).decode("utf-8")
        
        # Call Azure ML endpoint
        token = await self.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "current_image": base64_image,
            "indication": indication
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(self.endpoint, json=payload, headers=headers) as resp:
                result = await resp.json()
                return result["findings"]
```

#### Example 3: External REST API
**ClinicalTrials agent** → clinicaltrials.gov API

```python
# src/scenarios/default/tools/clinical_trials.py
class ClinicalTrialsPlugin:
    @kernel_function()
    async def search_clinical_trials(self, query: str) -> str:
        """Search clinicaltrials.gov for matching trials"""
        url = "https://clinicaltrials.gov/api/v2/studies"
        params = {"query.term": query}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                return self._format_results(data)
```

### Key Insight: Infinite Connectivity Possibilities

**The orchestrator doesn't care about your data sources or models!**

As long as you:
1. Create a tool/plugin that exposes the right interface (`create_plugin()` factory)
2. Register it in `agents.yaml` under an agent's `tools` list
3. Provide configuration (URLs, keys, etc.) via environment variables or agent config

...then ANY system can become a tool:
- ✅ REST APIs (public or private)
- ✅ Azure services (OpenAI, Cognitive Services, Azure ML)
- ✅ Databases (SQL, Cosmos, etc.)
- ✅ Enterprise systems (EHR, PACS, etc.)
- ✅ Other AI models (open-source, commercial)
- ✅ Computational tools (simulation, analysis)

---

## Part 4: Integration Ecosystem

### Microsoft Teams Integration

**How it works:**
1. Each agent gets its own Azure Bot Service resource
2. Bot receives messages via Bot Framework
3. Messages are routed to the orchestrator
4. Responses flow back through Bot Framework to Teams

**File:** `/src/app.py`

```python
# Create Teams-specific adapters for each agent
adapters = {
    agent["name"]: CloudAdapter(
        ConfigurationBotFrameworkAuthentication(
            DefaultConfig(botId=agent["bot_id"])
        )
    ).use(ShowTypingMiddleware()).use(AccessControlMiddleware())
    for agent in app_context.all_agent_configs
}

# Create bot instances
bots = {
    agent["name"]: AssistantBot(bot_config, agent)
    for agent in app_context.all_agent_configs
}
```

**User Experience:**
- Each agent appears as a separate bot in Teams
- Users mention agents: `@Orchestrator prepare tumor board for patient_4`
- Multi-agent conversations happen in Teams chat
- Responses include rich formatting, links to source data

**Deployment:**
- `infra/modules/botservice.bicep` - Azure Bot Service resources
- `scripts/generateTeamsApp.sh` - Creates Teams app packages
- `scripts/uploadPackage.sh` - Deploys to Teams

### Copilot Studio via Model Context Protocol (MCP)

**What is MCP?**
- Open protocol for agent-to-agent communication
- Each HAO agent exposed as an MCP "tool"
- Copilot Studio can discover and invoke HAO agents

**File:** `/src/mcp_app.py`

```python
def create_fast_mcp_app(app_ctx: AppContext) -> Starlette:
    """Expose HAO agents as MCP tools"""
    
    def create_app(session_id):
        app = FastMCP("Healthcare Agent Orchestrator")
        
        # Each agent becomes an MCP tool
        for agent in agent_config:
            app.add_tool(
                name=agent["name"],
                description=agent["description"],
                fn=generate_tool_function(agent["name"]),
            )
        
        return app
    
    # MCP server runs at /mcp/orchestrator
    return Starlette(
        routes=[Mount("/mcp", create_mcp_server())],
        lifespan=lifespan
    )
```

**Integration Flow:**
1. Create custom MCP connector in Copilot Studio (see `docs/mcp.md`)
2. Point connector to `https://{your-hao-deployment}/mcp/orchestrator`
3. Create Copilot agent that uses the connector
4. Copilot discovers all HAO agents as tools
5. Copilot can orchestrate HAO agents OR HAO orchestrator can manage the workflow

**Benefits:**
- Access HAO from M365 Copilot
- Enterprise governance (DLP, virtual networks)
- Unified experience across Microsoft ecosystem

**Configuration Example:**
```yaml
# Swagger definition for Copilot Studio connector
host: your-hao-deployment.azurewebsites.net
basePath: /mcp
paths:
  /orchestrator/:
    post:
      summary: MCP server Healthcare Agent Orchestrator
      operationId: InvokeMCP
      tags:
        - Agentic
        - McpStreamable
```

---

## Notable Code Modules

### High-Level Module Overview

```
src/
├── app.py                           # Application entry point, FastAPI setup
├── config.py                        # Configuration loading (agents.yaml, logging)
├── group_chat.py                    # ⭐ ORCHESTRATOR CORE - agent coordination
├── mcp_app.py                       # MCP server for Copilot integration
│
├── bots/                            # Teams Bot Framework integration
│   ├── assistant_bot.py             # Main bot handler
│   ├── access_control_middleware.py # Security: user/tenant authorization
│   └── show_typing_middleware.py    # UX: "typing" indicator in Teams
│
├── data_models/                     # ⭐ DATA ACCESS LAYER
│   ├── data_access.py               # Factory for data accessors
│   ├── clinical_note_accessor.py    # Blob storage implementation
│   ├── image_accessor.py            # Medical image retrieval
│   ├── chat_context.py              # Session state
│   ├── chat_artifact_accessor.py    # Agent-generated data
│   ├── plugin_configuration.py      # Configuration passed to tools
│   ├── fhir/
│   │   └── fhir_clinical_note_accessor.py  # FHIR implementation
│   └── fabric/
│       └── fabric_clinical_note_accessor.py # Fabric implementation
│
├── healthcare_agents/               # Custom agent implementations
│   ├── agent.py                     # HealthcareAgent class (external service wrapper)
│   └── client.py                    # Client for Healthcare Agent Service API
│
├── scenarios/                       # Scenario-specific configurations
│   └── default/
│       ├── config/
│       │   ├── agents.yaml          # ⭐ AGENT DEFINITIONS
│       │   └── openapi/             # OpenAPI specs for agent tools
│       └── tools/                   # ⭐ AGENT TOOLS/PLUGINS
│           ├── patient_data.py      # Patient timeline, Q&A
│           ├── cxr_report_gen.py    # Radiology model integration
│           ├── graph_rag.py         # Research search
│           ├── clinical_trials.py   # Clinical trial search
│           └── content_export.py    # Word doc generation
│
├── routes/                          # REST API endpoints
│   ├── api/                         # API routes (messages, chats)
│   ├── patient_data/                # Patient data serving
│   └── views/                       # Source data views
│
├── evaluation/                      # Agent evaluation framework
└── utils/                           # Utilities (logging, model helpers)
```

### Key Files Deep Dive

#### 1. **`/src/group_chat.py`** - The Orchestration Engine
**Lines of Interest:**
- `create_group_chat()` (line ~109): Main entry point
- `_create_agent()` (line ~132): Agent instantiation logic
- Selection prompt (line ~204): How next agent is chosen
- Termination prompt (line ~246): When to end conversation

**What it does:**
- Creates Semantic Kernel AgentGroupChat
- Implements selection strategy (LLM-based)
- Implements termination strategy
- Dynamically loads agent tools from `scenarios/{scenario}/tools/`

#### 2. **`/src/scenarios/default/config/agents.yaml`** - Agent Definitions
**What it defines:**
- All agents in the system (Orchestrator, PatientHistory, Radiology, etc.)
- Agent instructions (system prompts)
- Agent tools/plugins
- Agent-specific configuration (model endpoints, etc.)

**Example walkthrough:**
```yaml
- name: PatientHistory               # Identifier
  instructions: |                     # System prompt with step-by-step logic
    1. Request Patient ID if not provided
    2. Load data using `load_patient_data` tool
    3. Create timeline using `create_timeline` tool
    4. Present data without alterations
    5. Yield back: "back to you: *Orchestrator*"
  tools:                              # Tools this agent can use
    - name: patient_data              # References /tools/patient_data.py
  description: |                      # Used by orchestrator for routing
    A patient history agent. **You provide**: timeline. **You need**: patient ID.
  temperature: 0                      # Deterministic (no randomness)
```

#### 3. **`/src/data_models/data_access.py`** - Data Abstraction
**Lines of Interest:**
- `DataAccess` class (line ~82): Composite of all accessors
- `create_data_access()` (line ~97): Factory that switches data sources

**What it does:**
- Provides unified interface for all data operations
- Switches between Blob/FHIR/Fabric based on `CLINICAL_NOTES_SOURCE` env var
- Injected into agent tools via `PluginConfiguration`

#### 4. **`/src/data_models/chat_context.py`** - Session State
**What it stores:**
```python
class ChatContext:
    conversation_id: str              # Session identifier
    chat_history: ChatHistory         # Full conversation history
    patient_id: str                   # Current patient being discussed
    patient_data: list[dict]          # Loaded patient metadata
    display_blob_urls: list[str]      # URLs for generated artifacts
    output_data: list                 # Agent outputs
    healthcare_agents: dict           # External agent state
```

**Lifecycle:**
1. User sends message → load ChatContext from blob storage
2. Conversation happens → ChatContext accumulates history
3. User sends "clear" → archive ChatContext, create new one

#### 5. **`/src/scenarios/default/tools/patient_data.py`** - Tool Example
**Key Functions:**
- `create_plugin()`: Factory function (required by HAO)
- `load_patient_data()`: Loads clinical notes and images
- `create_timeline()`: Generates chronological patient timeline
- `process_prompt()`: Q&A over patient data using LLM

**Shows:**
- How tools access DataAccess
- How tools use LLMs (for structured outputs)
- How tools cache results in ChatArtifact

#### 6. **`/src/healthcare_agents/agent.py`** - Custom Agent Example
**What it is:**
- Custom agent class that delegates to external service
- No local LLM - just a wrapper/proxy
- Implements Semantic Kernel Agent interface

**Use case:**
- When you have an existing agent service
- When you want to isolate complex logic in a microservice
- When you need different runtime environments

#### 7. **`/src/mcp_app.py`** - MCP Server
**What it does:**
- Exposes each HAO agent as an MCP tool
- Manages MCP sessions (stateless HTTP)
- Handles conversation state per session
- Provides reset functionality

**Integration:**
- Used by Copilot Studio
- Could be used by any MCP-compatible client
- Demonstrates interoperability

---

## Other Technical Details

### Authentication & Authorization

**File:** `/src/bots/access_control_middleware.py`

```python
class AccessControlMiddleware:
    """Validates users/tenants are authorized to use the system"""
    
    async def on_turn(self, context: TurnContext, next_handler: Callable):
        # Check if user's tenant is allowed
        if not self._is_tenant_allowed(context):
            await context.send_activity("Access denied: tenant not authorized")
            return
        
        # Check if user ID is allowed
        if not self._is_user_allowed(context):
            await context.send_activity("Access denied: user not authorized")
            return
        
        await next_handler()
```

**Configuration:** Environment variables
- `ADDITIONAL_ALLOWED_TENANT_IDS`: Comma-separated tenant IDs
- `ADDITIONAL_ALLOWED_USER_IDS`: Comma-separated user IDs
- Default: `"*"` (allow all)

### Evaluation Framework

**Directory:** `/src/evaluation/`

**Purpose:**
- Automated testing of agents
- Synthetic conversation generation
- Quality metrics (faithfulness, relevance, etc.)

**See:** `docs/evaluation.md` for full guide

### Infrastructure as Code

**Directory:** `/infra/`

**Key files:**
- `main.bicep`: Main infrastructure template
- `modules/`: Individual resource modules (App Service, Bot Service, Storage, etc.)
- Multi-region support for GPU/GPT quota distribution

---

## Use Cases & Deployment Examples

### Tumor Board Preparation (Primary Use Case)

**Scenario:** Oncology team preparing for multidisciplinary tumor board

**Workflow:**
1. User: `@Orchestrator prepare tumor board for patient_4`
2. Orchestrator creates plan:
   - PatientHistory: Load clinical timeline
   - Radiology: Analyze recent imaging
   - PatientStatus: Summarize current status
   - ClinicalGuidelines: Recommend treatment
   - ClinicalTrials: Find eligible trials
   - MedicalResearch: Find relevant research
   - ReportCreation: Generate Word document
3. Each agent executes in sequence
4. Orchestrator synthesizes final report

**Time saved:** ~2-4 hours of manual preparation

### Clinical Research (Emerging Use Case)

**Scenario:** Research team analyzing cohorts across multiple data sources

**Custom Agents:**
- DataExploration: Query lakehouse with filters
- StatisticalAnalysis: Run R/Python analyses
- Visualization: Generate plots
- ReportGeneration: Create research report

**Data Sources:**
- Microsoft Fabric lakehouse
- Azure Synapse Analytics
- External research databases

### Patient Education (Concept)

**Scenario:** Translating medical jargon for patients

**Custom Agents:**
- Simplifier: Converts medical text to plain language
- GlossaryBuilder: Maintains patient-specific glossary
- Summarizer: Creates patient-friendly summaries

**Integration:**
- Patient portal
- Post-visit summaries

---

## Deployment Considerations

### Multi-Region Deployment

**Why:** GPU and GPT quota limitations

**How:**
```bash
# Set different regions for different resource types
azd env set AZURE_LOCATION "eastus"           # Primary region
azd env set AZURE_HLS_LOCATION "southcentral" # GPU models (A100)
azd env set AZURE_GPT_LOCATION "eastus2"      # GPT models
azd env set AZURE_APPSERVICE_LOCATION "eastus" # App Service
```

**Bicep:**
```bicep
// infra/main.bicep
param hlsLocation string = location                    // GPU region
param gptLocation string = location                    // GPT region
param appServiceLocation string = location              // App Service region

module hlsModel 'modules/hlsModel.bicep' = {
  name: 'hlsModelDeployment'
  params: {
    location: hlsLocation  // Deploy to GPU-available region
    ...
  }
}
```

### Security Considerations

1. **Network Isolation** (Optional):
   - Configure `ADDITIONAL_ALLOWED_IPS` for IP whitelisting
   - Use Azure Virtual Network integration
   - Private endpoints for storage/services

2. **Access Control**:
   - Tenant/user authorization middleware
   - Azure AD authentication for bot framework
   - Managed Identity for service-to-service auth

3. **Data Protection**:
   - PHI/PII considerations (HAO not intended for identifiable data)
   - Encryption at rest (Azure Storage)
   - Encryption in transit (HTTPS, TLS)

### Scaling

**Horizontal Scaling:**
- App Service Plan: Scale out to multiple instances
- Bot messages load-balanced automatically

**Vertical Scaling:**
- App Service SKU: P1v3, P2v3, P3v3 for more CPU/memory
- Consider GPU SKU for model endpoints

**Cost Optimization:**
- Use Azure OpenAI provisioned throughput for predictable costs
- Consider serverless GPU endpoints for sporadic workloads

---

## Summary: Key Takeaways

### For the Workshop

1. **Orchestration**: HAO coordinates multi-agent conversations using Semantic Kernel's AgentGroupChat with LLM-based selection/termination strategies

2. **Flexibility**: Agents are defined in YAML, tools are Python plugins - easy to extend without code changes to the core

3. **Data Agnostic**: Data access layer abstracts Blob/FHIR/Fabric - agents don't know or care about the source

4. **Model Agnostic**: Agents can wrap any AI system - LLMs, Azure ML models, external APIs, rule engines

5. **Enterprise Ready**: Teams integration, Copilot Studio via MCP, multi-region deployment, access control

6. **Open Architecture**: Not locked into Microsoft - MCP is open protocol, can integrate with any system

### What Makes HAO Unique

- **Configuration-driven**: Add agents via YAML, not code
- **Turn-based orchestration**: Clear reasoning about agent interactions
- **Healthcare-focused patterns**: FHIR, medical imaging, clinical guidelines
- **Research-informed**: Based on validated components (CXRReportGen, GraphRAG, etc.)
- **Production-ready**: IaC, monitoring, security, scalability built-in

### Next Steps for Customers

1. **Proof of Concept**: Deploy default scenario, test with sample data
2. **Data Integration**: Connect to FHIR server or custom data source
3. **Custom Agents**: Define agents for their specific workflows
4. **Custom Tools**: Integrate with their enterprise systems
5. **Evaluation**: Use evaluation framework to measure quality
6. **Production Deployment**: Multi-region, security hardening, monitoring

---

## Q&A Preparation

### Common Questions

**Q: Can we use models other than Azure OpenAI?**  
A: Yes! Agents can use any model accessible via API. The framework uses Semantic Kernel, which supports multiple providers (OpenAI, Azure OpenAI, Hugging Face, etc.). Custom agents can use any model.

**Q: How do we handle PHI/PII?**  
A: HAO is designed for research/development, not production clinical use as-is. For PHI:
- De-identify data before ingestion
- Use Azure services with HIPAA compliance (Azure OpenAI, Storage)
- Enable encryption, audit logging, access controls
- Consult with legal/compliance teams

**Q: What's the cost?**  
A: Primary costs are:
- Azure OpenAI (GPT-4o/4.1): $5-$15 per 1M tokens
- GPU compute for models (A100): ~$3/hour
- App Service: ~$200-500/month (P1v3-P2v3)
- Storage: Negligible (<$10/month)
- Bot Service: Free (standard tier)

Typical tumor board prep: ~$0.50-2.00 depending on data volume.

**Q: How long does deployment take?**  
A: 
- Infrastructure (azd up): 30-45 minutes
- CXRReportGen model download: 60-90 minutes (one-time)
- Total first deployment: ~2 hours
- Subsequent deployments: ~10-15 minutes

**Q: Can we deploy on-premises?**  
A: HAO requires Azure services (OpenAI, Storage, Bot Service). Hybrid options:
- Azure Stack for some services
- Use Azure Arc for on-prem compute
- Connect to on-prem FHIR servers from Azure

**Q: How do we add our own agent?**  
A: Three steps:
1. Add entry to `scenarios/default/config/agents.yaml`
2. (Optional) Create tools in `scenarios/default/tools/`
3. Deploy: `azd up`

See `docs/agent_development.md` for full guide.

**Q: What's the difference between HAO orchestrator and Semantic Kernel's orchestration?**  
A: HAO uses Semantic Kernel but adds:
- Healthcare-specific patterns (FHIR, medical imaging)
- Configuration-driven agent definition (YAML)
- Teams/Copilot integration
- Data access abstraction
- Production infrastructure (IaC)

Semantic Kernel is the framework; HAO is an accelerator built on it.

**Q: Can agents run in parallel?**  
A: Not in current implementation. Agents execute sequentially in a turn-based fashion. For parallel execution, you would need to modify the orchestration strategy or use async message queues.

**Q: How do we monitor agent performance?**  
A: 
- Application Insights: Logs, traces, exceptions
- Semantic Kernel telemetry: Function calls, LLM usage
- Custom evaluation metrics (see `docs/evaluation.md`)
- Azure Monitor dashboards

---

## Additional Resources

- **Main Documentation:** `/docs/README.md`
- **Agent Development:** `/docs/agent_development.md`
- **FHIR Integration:** `/docs/fhir_integration.md`
- **Data Ingestion:** `/docs/data_ingestion.md`
- **Evaluation Guide:** `/docs/evaluation.md`
- **MCP Integration:** `/docs/mcp.md`
- **Troubleshooting:** `/docs/troubleshooting.md`

---

**End of Workshop Guide**
