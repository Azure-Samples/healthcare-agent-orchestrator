# Patient Context Management - Comprehensive Guide

This document provides a complete analysis of the **Patient Context Management System** migration from a single-conversation model to a multi-patient, registry-backed architecture with ephemeral snapshot grounding.

> [!IMPORTANT]
> This is a technical deep-dive document. For quick reference, see [`patient_context.md`](patient_context.md).

---

## Table of Contents

- [Executive Summary](#executive-summary)
- [Architecture Overview](#architecture-overview)
- [New Components](#new-components)
- [Modified Components](#modified-components)
- [Complete Turn Flow](#complete-turn-flow)
- [Migration Benefits](#migration-benefits)

---

## Executive Summary

The Healthcare Agent Orchestrator has been enhanced with a **registry-backed, ephemeral snapshot architecture** to enable multi-patient conversational state management within a single conversation.

### Key Achievements

| Capability | Before | After |
|------------|--------|-------|
| **Patient Isolation** | Single conversation = single context | Multiple patients with isolated histories |
| **Patient Switching** | Not supported | Seamless switching with kernel reset |
| **Storage Model** | Single `chat_context.json` | Per-patient files + session + registry |
| **Agent Grounding** | No patient awareness | Ephemeral snapshot each turn |
| **Clear Operation** | Simple archive | Bulk archive (session + all patients + registry) |
| **Patient Detection** | Manual/hardcoded | Automatic LLM-based classifier |
| **Orchestration** | Facilitator loops, false terminations | Confirmation gate + termination overrides |

---

## Architecture Overview

### Old Architecture (Single Context Model)

```
┌─────────────────────────────────────────────────────────┐
│                    User Interface                        │
│              (Teams Bot / WebSocket API)                 │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ↓
           ┌───────────────────────┐
           │   ChatContext         │
           │  - conversation_id    │
           │  - chat_history       │ ← Single history
           │  - patient_id (unused)│
           └───────────┬───────────┘
                       │
                       ↓
           ┌───────────────────────┐
           │  Storage (Blob)       │
           │  {conv_id}/           │
           │    chat_context.json  │ ← One file
           └───────────────────────┘
```

**Problems:**
- ❌ No patient isolation (all messages in one history)
- ❌ No patient switching capability
- ❌ No patient awareness in agents
- ❌ Facilitator loops (no confirmation gate)
- ❌ False terminations (snapshot messages confused LLM)

### New Architecture (Registry-Backed Ephemeral Model)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User Interface                               │
│                   (Teams Bot / WebSocket API)                        │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ↓
        ┌───────────────────────────────────────────┐
        │   PatientContextService                   │
        │   - decide_and_apply()                    │
        │   - Registry hydration                    │
        │   - Silent restore                        │
        │   - Validation                            │
        └──────────┬────────────────────────────────┘
                   │
      ┌────────────┴─────────────┐
      │                          │
      ↓                          ↓
┌─────────────────┐    ┌──────────────────────┐
│ PatientContext  │    │ Registry Accessor    │
│ Analyzer        │    │ (Source of Truth)    │
│ - LLM Classifier│    │                      │
│ - Structured    │    │ registry.json:       │
│   Output        │    │ - active_patient_id  │
│ - Intent        │    │ - patient_registry   │
│   Detection     │    │   map                │
└─────────────────┘    └──────────┬───────────┘
                                  │
                    ┌─────────────┴──────────────────────┐
                    │                                     │
                    ↓                                     ↓
          ┌──────────────────┐              ┌───────────────────────┐
          │  ChatContext     │              │  Storage (Blob)       │
          │  - conversation_id│             │  {conv_id}/           │
          │  - patient_id    │              │   session_context.json│
          │  - patient_contexts│            │   patient_4_context   │
          │  - chat_history  │◄────────────┤   patient_15_context  │
          └────────┬─────────┘              │   registry.json       │
                   │                        └───────────────────────┘
                   │
                   ↓
    ┌──────────────────────────────────┐
    │  Ephemeral Snapshot Injection    │
    │  [0] SYSTEM: PATIENT_CONTEXT_JSON│ ← Generated each turn
    │  [1] USER: message               │
    │  [2] ASSISTANT: response         │
    └──────────┬───────────────────────┘
               │
               ↓
    ┌──────────────────────────┐
    │  Group Chat              │
    │  - Selection (w/ gate)   │
    │  - Termination (w/       │
    │    overrides)            │
    │  - Agents (see snapshot) │
    └──────────────────────────┘
```

**Benefits:**
- ✅ **Per-patient isolation** - Separate history files
- ✅ **Multi-patient roster** - Registry tracks all patients in session
- ✅ **Ephemeral grounding** - Fresh snapshot each turn (never persisted)
- ✅ **Automatic detection** - LLM analyzer classifies intent
- ✅ **Safe switching** - Kernel reset on patient change
- ✅ **Robust clear** - Bulk archive with timestamp folders
- ✅ **Stable orchestration** - Confirmation gate + deterministic overrides

---

## New Components

### 1. PatientContextAnalyzer

**File:** `src/services/patient_context_analyzer.py`

**Purpose:** LLM-based structured output classifier that determines patient context intent from user messages.

**Key Features:**

```python
class PatientContextAnalyzer:
    """
    Analyzes user messages to determine patient context actions.
    Uses Azure OpenAI with structured output for reliable classification.
    """
    
    async def analyze_patient_context(
        self,
        user_text: str,
        prior_patient_id: str | None,
        known_patient_ids: list[str]
    ) -> PatientContextDecision:
        """
        Returns structured decision:
        - action: NONE | ACTIVATE_NEW | SWITCH_EXISTING | UNCHANGED | CLEAR
        - patient_id: Extracted ID (for ACTIVATE_NEW/SWITCH_EXISTING only)
        - reasoning: Brief explanation
        """
```

**Decision Examples:**

| User Input | Context | Action | patient_id | Reasoning |
|------------|---------|--------|------------|-----------|
| `"review patient_4"` | No active | `ACTIVATE_NEW` | `"patient_4"` | User explicitly requests patient_4 |
| `"switch to patient_15"` | patient_4 active | `SWITCH_EXISTING` | `"patient_15"` | Explicit switch requested |
| `"what's the diagnosis?"` | patient_4 active | `UNCHANGED` | `null` | Follow-up question for active patient |
| `"clear patient"` | patient_4 active | `CLEAR` | `null` | User requests context reset |

**Heuristic Skip:**
- Messages ≤ 15 characters without keywords (`patient`, `clear`, `switch`) bypass the analyzer for efficiency
- Returns `UNCHANGED` if patient active, `NONE` otherwise

**Why This Component:**
- **Automatic** - No manual parsing/regex
- **Contextual** - Considers prior state and known patients
- **Reliable** - Structured output ensures consistent format
- **Explainable** - Reasoning field aids debugging
- **Efficient** - Heuristic skip for short messages

---

### 2. PatientContextService

**File:** `src/services/patient_context_service.py`

**Purpose:** Orchestrates the complete patient context lifecycle - hydration, analysis, validation, and application.

**Key Methods:**

```python
class PatientContextService:
    """
    Manages patient context lifecycle:
    - Registry hydration
    - Silent restoration
    - Analyzer invocation
    - Decision validation & application
    - Side effects (kernel reset, archival)
    """
    
    async def decide_and_apply(
        self,
        user_text: str,
        chat_ctx: ChatContext
    ) -> tuple[Decision, TimingInfo]:
        """
        Main orchestration method. Returns:
        - Decision: Final service decision
        - TimingInfo: Performance metrics
        """
```

**Decision Pipeline:**

```
User Text
  ↓
1. Hydrate Registry → chat_ctx.patient_contexts
  ↓
2. Silent Restore Attempt (if no active patient)
  ↓
3. Heuristic Check (skip analyzer if short message)
  ↓
4. Analyzer Invocation (if not skipped)
  ↓
5. Validation & Transformation:
   - ACTIVATE_NEW + new ID → NEW_BLANK
   - ACTIVATE_NEW + exists → SWITCH_EXISTING
   - ACTIVATE_NEW + invalid → NEEDS_PATIENT_ID
   - SWITCH_EXISTING + invalid → NEEDS_PATIENT_ID
   - CLEAR → archive + reset
  ↓
6. Apply Side Effects:
   - Kernel reset (if patient change)
   - Registry update
   - Archive (if clear)
  ↓
7. Return (Decision, TimingInfo)
```

**Service Decisions:**

```
"NONE"                    - No patient context change
"UNCHANGED"               - Keep current patient
"NEW_BLANK"               - Activate new patient (reinterpreted ACTIVATE_NEW)
"SWITCH_EXISTING"         - Switch to known patient
"CLEAR"                   - Archive all and reset
"RESTORED_FROM_STORAGE"   - Silent reactivation from registry
"NEEDS_PATIENT_ID"        - User intent unclear, need valid ID
```

**Why This Component:**
- **Centralized orchestration** - Single responsibility for patient lifecycle
- **Consistent validation** - Regex pattern enforced (`PATIENT_ID_PATTERN`)
- **Registry authority** - Always syncs with source of truth
- **Performance tracking** - TimingInfo for monitoring
- **Separation of concerns** - Service doesn't inject snapshots (caller responsibility)

---

### 3. PatientContextRegistry Accessor

**File:** `src/data_models/patient_context_registry_accessor.py`

**Purpose:** Manages persistence of the patient context registry (source of truth).

**Registry Structure:**

```json
{
  "active_patient_id": "patient_4",
  "patient_registry": {
    "patient_4": {
      "patient_id": "patient_4",
      "facts": {},
      "conversation_id": "19:abc-123-def@thread.tacv2",
      "created_at": "2025-09-30T16:30:00.000Z",
      "updated_at": "2025-09-30T16:45:00.000Z"
    },
    "patient_15": {
      "patient_id": "patient_15",
      "facts": {},
      "conversation_id": "19:abc-123-def@thread.tacv2",
      "created_at": "2025-09-30T16:32:00.000Z",
      "updated_at": "2025-09-30T16:40:00.000Z"
    }
  }
}
```

**Key Methods:**

```python
class PatientContextRegistryAccessor:
    async def read_registry(
        self,
        conversation_id: str
    ) -> tuple[dict, str | None]:
        """Returns (patient_registry, active_patient_id)"""
    
    async def write_registry(
        self,
        conversation_id: str,
        patient_registry: dict,
        active_patient_id: str | None
    ) -> None:
        """Persists registry to patient_context_registry.json"""
    
    async def archive_registry(
        self,
        conversation_id: str
    ) -> None:
        """Archives registry during clear operation"""
```

**Why This Component:**
- **Source of truth** - Registry is authoritative for active patient
- **Roster management** - Tracks all patients in session
- **Extensible facts** - Can store patient-specific metadata
- **Audit trail** - Timestamps for compliance
- **Archival support** - Clean clear operations

---

### 4. PatientContext Data Models

**File:** `src/data_models/patient_context_models.py`

**Purpose:** Type-safe models for patient context operations.

**Key Models:**

```python
class PatientContext:
    """Represents a patient's context within a conversation."""
    patient_id: str
    facts: dict = field(default_factory=dict)
    conversation_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PatientContextDecision:
    """Structured output from PatientContextAnalyzer."""
    action: Literal["NONE", "ACTIVATE_NEW", "SWITCH_EXISTING", "UNCHANGED", "CLEAR"]
    patient_id: Optional[str] = None
    reasoning: str


class TimingInfo:
    """Performance metrics for patient context operations."""
    analyzer_ms: Optional[float] = None
    storage_fallback_ms: Optional[float] = None
    service_total_ms: Optional[float] = None
```

**Why These Models:**
- **Type safety** - Catches errors at development time
- **Documentation** - Clear contracts for each component
- **Extensibility** - Easy to add new fields (e.g., `facts`)
- **Structured output** - Enforces LLM output format
- **Observability** - Timing metrics for monitoring

---

## Modified Components

### 1. ChatContext Data Model

**File:** `src/data_models/chat_context.py`

#### Before:

```python
class ChatContext:
    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.chat_history = ChatHistory()
        self.patient_id = None  # ← Unused field
        # ... other fields
```

#### After:

```python
class ChatContext:
    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.chat_history = ChatHistory()
        self.patient_id = None  # ← NOW USED: Active patient pointer
        self.patient_contexts: Dict[str, PatientContext] = {}  # ✅ NEW: Multi-patient roster
        # ... other fields
```

**Key Changes:**

| Field | Before | After |
|-------|--------|-------|
| `patient_id` | Unused | **Active patient pointer** (set by service) |
| `patient_contexts` | ❌ N/A | ✅ **Dict[str, PatientContext]** - roster of all patients |
| `chat_history` | Single history | **Swapped per-patient** (loaded from isolated files) |

**Lifecycle Example:**

```python
# Turn 1: User mentions patient_4
chat_ctx.patient_id = None
chat_ctx.patient_contexts = {}
  ↓ decide_and_apply()
chat_ctx.patient_id = "patient_4"
chat_ctx.patient_contexts = {
    "patient_4": PatientContext(patient_id="patient_4", ...)
}

# Turn 2: User switches to patient_15
  ↓ decide_and_apply()
chat_ctx.patient_id = "patient_15"
chat_ctx.patient_contexts = {
    "patient_4": ...,
    "patient_15": PatientContext(patient_id="patient_15", ...)
}
```

---

### 2. ChatContextAccessor (Storage Layer)

**File:** `src/data_models/chat_context_accessor.py`

This is one of the **most critical** changes - the accessor now handles per-patient file routing and ephemeral snapshot filtering.

#### A. `get_blob_path()` - File Routing

##### Before:
```python
def get_blob_path(self, conversation_id: str) -> str:
    return f"{conversation_id}/chat_context.json"  # Single file
```

##### After:
```python
def get_blob_path(self, conversation_id: str, patient_id: str = None) -> str:
    if patient_id:
        return f"{conversation_id}/patient_{patient_id}_context.json"
    return f"{conversation_id}/session_context.json"
```

**Storage Structure:**

```
BEFORE:
conversation_123/
  └── chat_context.json  ← All messages

AFTER:
conversation_123/
  ├── session_context.json            ← Session-level (no patient)
  ├── patient_patient_4_context.json  ← patient_4's history
  ├── patient_patient_15_context.json ← patient_15's history
  └── patient_context_registry.json   ← Source of truth
```

#### B. `serialize()` - Ephemeral Snapshot Filtering

This is **CRITICAL** - ensures snapshots never get persisted.

##### Before:
```python
@staticmethod
def serialize(chat_ctx: ChatContext) -> str:
    return json.dumps({
        "chat_history": chat_ctx.chat_history.serialize(),  # Direct
    })
```

##### After:
```python
@staticmethod
def serialize(chat_ctx: ChatContext) -> str:
    chat_messages = []
    skipped_pc = 0
    
    for msg in chat_ctx.chat_history.messages:
        # Extract content
        content = extract_content(msg)
        
        # ✅ FILTER: Skip ephemeral patient context snapshot
        if msg.role == AuthorRole.SYSTEM and content.startswith(PATIENT_CONTEXT_PREFIX):
            skipped_pc += 1
            continue  # ← CRITICAL: Don't persist snapshot
        
        chat_messages.append({...})
    
    return json.dumps({"chat_history": chat_messages, ...})
```

**Filtering in Action:**

```python
# In-memory (what agents see):
[
    [0] SYSTEM: "PATIENT_CONTEXT_JSON: {...}",  ← Ephemeral
    [1] USER: "review patient_4",
    [2] ASSISTANT: "Plan: ..."
]

# Persisted (what gets saved):
[
    [0] USER: "review patient_4",  ← Snapshot filtered out
    [1] ASSISTANT: "Plan: ..."
]
```

**Why This Is Critical:**
- **Ephemeral only** - Snapshot never pollutes storage
- **Registry as truth** - Active patient always from registry, not stale snapshot
- **Fresh every turn** - Rebuilt from registry each time
- **No staleness** - Can't have outdated patient context

---

### 3. Healthcare Agents

**File:** `src/healthcare_agents/agent.py`

#### Message Structure Change

##### Before:
```python
response_message = ChatMessageContent(
    role=AuthorRole.ASSISTANT,
    name=agent.name,
    content=response_dict.get("text", "")  # ❌ Direct content
)
```

##### After:
```python
response_message = ChatMessageContent(
    role=AuthorRole.ASSISTANT,
    name=agent.name,
    items=[TextContent(text=response_dict.get("text", ""))]  # ✅ Structured
)
```

**Why This Change:**
- **Consistent structure** - Aligns with Semantic Kernel message format
- **Enables filtering** - Accessor can reliably detect snapshot messages
- **Required for serialization** - Accessor expects `items` structure

---

### 4. Group Chat Orchestration

**File:** `src/group_chat.py`

#### A. CONFIRMATION GATE (Selection Prompt)

Added to selection function prompt:

```python
"""
- **CONFIRMATION GATE (PLAN ONLY)**: 
  If (a) the MOST RECENT message is from {facilitator} AND 
     (b) it contains a multi-step plan (look for "Plan", "plan:", 
         numbered steps like "1.", "2.", or bullet lines) AND 
     (c) no user message has appeared AFTER that plan yet, 
  then do NOT advance to another agent. Wait for a user reply.
"""
```

**Before:**
```
User: "review patient_4"
Orchestrator: "Plan: 1. PatientHistory, 2. Radiology..."
PatientHistory: [starts immediately] ❌
```

**After:**
```
User: "review patient_4"
Orchestrator: "Plan: 1. PatientHistory, 2. Radiology..."
Selection: 🛑 GATE TRIGGERED - wait for user
Orchestrator: "Does this plan work for you?"
User: "yes proceed"
Selection: Gate lifted → PatientHistory ✅
```

#### B. Termination Overrides (Deterministic)

Added to `evaluate_termination()`:

```python
def evaluate_termination(result):
    # NEW: Pre-check before LLM evaluation
    try:
        last_text = extract_last_message_text(chat_ctx)
        
        # Override 1: Ignore patient context snapshots
        if last_text.lower().startswith("patient_context_json"):
            return False  # Continue
        
        # Override 2: Ignore internal handoffs
        if "back to you" in last_text.lower():
            return False  # Continue
    except Exception:
        pass
    
    # Fall back to LLM verdict
    rule = ChatRule.model_validate_json(str(result.value[0]))
    return rule.verdict == "yes"
```

**Why These Changes:**
- **Prevents facilitator loops** - Waits for user confirmation before executing plan
- **Prevents false termination** - System messages don't end conversation
- **Allows agent handoffs** - "back to you X" continues orchestration
- **Deterministic** - Python logic for unambiguous cases (faster, more reliable)

---

### 5. Entry Points (Assistant Bot & API Routes)

**Files:** `src/bots/assistant_bot.py`, `src/routes/api/chats.py`

Both entry points follow the **identical pattern**:

#### Complete Turn Flow

```python
async def on_message_activity(self, turn_context: TurnContext):
    conversation_id = turn_context.activity.conversation.id
    raw_user_text = extract_user_text(turn_context)
    
    # STEP 1: Load session context
    chat_ctx = await chat_context_accessor.read(conversation_id, None)
    
    # STEP 2: Check clear command
    if await self._handle_clear_command(raw_user_text, chat_ctx, conversation_id):
        await send_cleared_message()
        return
    
    # STEP 3: Patient context decision
    decision, timing = await self.patient_context_service.decide_and_apply(
        raw_user_text, chat_ctx
    )
    
    # STEP 4: Handle NEEDS_PATIENT_ID
    if decision == "NEEDS_PATIENT_ID":
        await send_error_message("I need a patient ID like 'patient_4'")
        return
    
    # STEP 5: Load isolated patient history
    if chat_ctx.patient_id:
        isolated = await chat_context_accessor.read(conversation_id, chat_ctx.patient_id)
        if isolated and isolated.chat_history.messages:
            chat_ctx.chat_history = isolated.chat_history
    
    # STEP 5.5: Inject fresh ephemeral snapshot
    chat_ctx.chat_history.messages = strip_old_snapshots(chat_ctx.chat_history.messages)
    
    snapshot = {
        "conversation_id": chat_ctx.conversation_id,
        "patient_id": chat_ctx.patient_id,
        "all_patient_ids": sorted(chat_ctx.patient_contexts.keys()),
        "generated_at": datetime.utcnow().isoformat() + "Z"
    }
    snapshot_msg = create_system_message(snapshot)
    chat_ctx.chat_history.messages.insert(0, snapshot_msg)
    
    # STEP 6: Group chat
    (chat, chat_ctx) = create_group_chat(app_context, chat_ctx)
    chat_ctx.chat_history.add_user_message(raw_user_text)
    
    # STEP 7: Process chat
    await self.process_chat(chat, chat_ctx, turn_context)
    
    # STEP 8: Save (snapshot auto-filtered)
    await chat_context_accessor.write(chat_ctx)
```

**Key Additions:**
1. **Patient context service** - Initialized in `__init__()`
2. **Enhanced clear** - `_handle_clear_command()` bulk archives
3. **Patient decision** - `decide_and_apply()` orchestration
4. **Isolated load** - Swaps in patient-specific history
5. **Ephemeral snapshot** - Fresh injection every turn
6. **PT_CTX footer** - Appended to agent responses (UI only)

---

## Complete Turn Flow

### Example: Multi-Patient Session

```
═══════════════════════════════════════════════════════════════
TURN 1: User mentions patient_4
═══════════════════════════════════════════════════════════════

User (Teams): "@Orchestrator start tumor board for patient_4"

[Entry Point: assistant_bot.on_message_activity]
  ↓
STEP 1: Load session_context.json
  Result: Empty ChatContext(conversation_id="abc123")
  ↓
STEP 2: Check clear → NOT a clear command
  ↓
STEP 3: Patient context decision
  ├─ Hydrate registry: {} (no registry yet)
  ├─ Analyzer input: "start tumor board for patient_4"
  ├─ Analyzer output: ACTIVATE_NEW (patient_id="patient_4")
  ├─ Validation: ✅ Valid pattern, not in registry
  ├─ Decision: NEW_BLANK
  ├─ Action: Create PatientContext, update registry
  └─ Result: patient_id="patient_4", registry written
  ↓
STEP 5: Load patient_patient_4_context.json
  → File doesn't exist (first time) → Empty history
  ↓
STEP 5.5: Inject ephemeral snapshot
  [0] SYSTEM: PATIENT_CONTEXT_JSON: {
        "patient_id": "patient_4",
        "all_patient_ids": ["patient_4"],
        ...
      }
  ↓
STEP 6: Add user message
  [1] USER: "start tumor board for patient_4"
  ↓
STEP 7: Orchestrator responds
  "Plan:
   1. *PatientHistory*: Load clinical timeline
   2. *Radiology*: Review imaging
   3. I'll compile recommendations
   
   Does this plan look good?"
  ↓
STEP 8: Save to patient_patient_4_context.json
  (Snapshot filtered out)

[Storage After Turn 1]
conversation_abc123/
├── patient_patient_4_context.json     ← Created
└── patient_context_registry.json      ← Created
    {
      "active_patient_id": "patient_4",
      "patient_registry": {
        "patient_4": {...}
      }
    }

═══════════════════════════════════════════════════════════════
TURN 2: User confirms plan
═══════════════════════════════════════════════════════════════

User: "yes proceed"

STEP 3: Patient context decision
  ├─ Hydrate registry: {"patient_4": ...}
  ├─ Analyzer: Short message heuristic → UNCHANGED
  └─ Result: Keep patient_4 active
  ↓
STEP 5: Load patient_patient_4_context.json
  Contains: Previous plan message
  ↓
STEP 5.5: Inject fresh snapshot
  [0] SYSTEM: PATIENT_CONTEXT_JSON: {...}  ← Fresh
  [1] USER: "start tumor board..."
  [2] ASSISTANT: "Plan: ..."
  [3] USER: "yes proceed"  ← New
  ↓
STEP 7: Orchestration
  ├─ Selection: User confirmed → PatientHistory
  ├─ PatientHistory: "Timeline for patient_4: ..."
  │   "Back to you Orchestrator."
  ├─ Termination: "back to you" detected → CONTINUE ✅
  ├─ Selection: Orchestrator
  └─ Orchestrator: "Moving to step 2. *Radiology*..."

═══════════════════════════════════════════════════════════════
TURN 3: User switches to different patient
═══════════════════════════════════════════════════════════════

User: "switch to patient_15"

STEP 3: Patient context decision
  ├─ Analyzer: ACTIVATE_NEW (patient_id="patient_15")
  ├─ Validation: Not in registry → NEW_BLANK
  ├─ Action: Create patient_15, kernel reset
  └─ Result: patient_id="patient_15"
  ↓
STEP 5: Load patient_patient_15_context.json
  → File doesn't exist → Empty history
  ↓
STEP 5.5: Inject snapshot
  [0] SYSTEM: PATIENT_CONTEXT_JSON: {
        "patient_id": "patient_15",  ← NEW ACTIVE
        "all_patient_ids": ["patient_4", "patient_15"],
        ...
      }
  ↓
STEP 7: Orchestrator
  "Switched to patient_15. What would you like to review?"

[Storage After Turn 3]
conversation_abc123/
├── patient_patient_4_context.json     ← Unchanged (isolated)
├── patient_patient_15_context.json    ← Created
└── patient_context_registry.json      ← Updated
    {
      "active_patient_id": "patient_15",  ← Changed
      "patient_registry": {
        "patient_4": {...},
        "patient_15": {...}  ← Added
      }
    }

═══════════════════════════════════════════════════════════════
TURN 4: Clear all patient contexts
═══════════════════════════════════════════════════════════════

User: "clear patient context"

STEP 2: Clear command detected ✅
  ↓
_handle_clear_command():
  ├─ Archive session_context.json
  ├─ Archive patient_patient_4_context.json
  ├─ Archive patient_patient_15_context.json
  ├─ Archive patient_context_registry.json
  ├─ All archived to: archive/20250930T164500/
  ├─ Delete all original files
  ├─ Reset in-memory state
  └─ Write empty session_context.json

[Storage After Clear]
conversation_abc123/
└── archive/
    └── 20250930T164500/
        └── conversation_abc123/
            ├── 20250930T164500_session_archived.json
            ├── 20250930T164500_patient_patient_4_archived.json
            ├── 20250930T164500_patient_patient_15_archived.json
            └── 20250930T164500_patient_context_registry_archived.json
```

---

## Migration Benefits

### Safety Improvements

| Before | After | Benefit |
|--------|-------|---------|
| ❌ All patients in same history | ✅ Separate files per patient | **No cross-contamination** |
| ❌ Agent sees all patient data | ✅ Agent sees only active patient | **Data isolation** |
| ❌ Switching loses context | ✅ Switching preserves history | **Context continuity** |
| ❌ No audit trail | ✅ Registry + archives | **Compliance & debugging** |

### User Experience Improvements

| Before | After | Benefit |
|--------|-------|---------|
| ❌ Manual patient tracking | ✅ Automatic detection | **Reduced friction** |
| ❌ No active patient visibility | ✅ PT_CTX footer every response | **Transparency** |
| ❌ Can't work on multiple patients | ✅ Multi-patient sessions | **Workflow flexibility** |
| ❌ Facilitator loops endlessly | ✅ Confirmation gate | **Plan validation** |

### Technical Improvements

| Before | After | Benefit |
|--------|-------|---------|
| ❌ Single storage file | ✅ Per-patient + session + registry | **Scalability** |
| ❌ No patient awareness | ✅ Ephemeral snapshots | **Agent grounding** |
| ❌ Simple clear | ✅ Bulk archive with timestamps | **Organized history** |
| ❌ False terminations | ✅ Deterministic overrides | **Stable orchestration** |
| ❌ Hardcoded patterns | ✅ Configurable via env var | **Flexibility** |

---

## Configuration

### Customizing Patient ID Format

Set the `PATIENT_ID_PATTERN` environment variable:

```bash
# Default: patient_<digits>
export PATIENT_ID_PATTERN="^patient_[0-9]+$"

# MRN format
export PATIENT_ID_PATTERN="^mrn-[A-Z0-9]{6}$"

# Multiple formats
export PATIENT_ID_PATTERN="^(patient_[0-9]+|mrn-[A-Z0-9]{6})$"
```

> [!IMPORTANT]
> When changing the pattern, update the analyzer prompt in `patient_context_analyzer.py` to match.

---

## Summary

The patient context system enables:

1. **Multi-patient conversations** - Work on multiple patients in one session
2. **Complete isolation** - Each patient's history stored separately
3. **Automatic detection** - LLM-based intent classification
4. **Safe switching** - Kernel reset prevents cross-contamination
5. **Ephemeral grounding** - Fresh snapshots never persisted
6. **Registry-backed** - Single source of truth for active patient
7. **Stable orchestration** - Confirmation gates + termination overrides
8. **Organized archival** - Timestamped bulk archives for compliance

For quick reference, see [`patient_context.md`](patient_context.md).

---

**Last Updated:** September 30, 2025  
**Status:** Stable in production (`sekar/pc_poc` branch)
