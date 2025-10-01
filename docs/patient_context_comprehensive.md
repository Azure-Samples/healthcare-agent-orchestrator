# Patient Context Management - Technical Guide

This document explains how the Healthcare Agent Orchestrator now handles **multiple patients in a single conversation** using a registry-backed architecture with ephemeral snapshots.

---

## Table of Contents

- [What Changed and Why](#what-changed-and-why)
- [How It Works Now](#how-it-works-now)
- [New Components](#new-components)
- [Modified Components](#modified-components)
- [Step-by-Step Turn Flow](#step-by-step-turn-flow)
- [Configuration](#configuration)

---

## What Changed and Why

### The Problem

**Before**, the system could only handle **one context per conversation**:

```
❌ All messages in one file (chat_context.json)
❌ No way to switch between patients
❌ Agents had no idea which patient they were discussing
❌ "Clear" just archived one file
```

**Example of the problem:**
```
User: "Review patient_4's labs"
[Agent responds about patient_4]
User: "Now check patient_15's imaging"
[Agent gets confused - both patients' messages mixed together]
```

### The Solution

**Now**, the system supports **multiple patients with isolated histories**:

```
✅ Each patient gets their own history file
✅ Registry tracks which patient is currently active
✅ Agents see a "snapshot" showing current patient context
✅ Switch between patients seamlessly
✅ Clear archives everything properly
```

**How it works now:**
```
User: "Review patient_4's labs"
[System activates patient_4, creates patient_4_context.json]
[Agent sees snapshot: "You're working on patient_4"]

User: "Now check patient_15's imaging"
[System switches to patient_15, creates patient_15_context.json]
[Agent sees new snapshot: "You're now working on patient_15"]
[patient_4's history is safely stored and separate]
```

### Quick Comparison

| Feature | Before | After |
|---------|--------|-------|
| **Storage** | 1 file for everything | Separate file per patient + registry |
| **Patient Switching** | Not supported | Automatic detection and switching |
| **Agent Awareness** | No idea about patient context | Fresh snapshot each turn |
| **Clear Command** | Archives 1 file | Archives all patient files + registry |
| **Patient Detection** | Manual/hardcoded | LLM automatically detects intent |

---

## How It Works Now

### Architecture Overview

```
User Message
    ↓
┌───────────────────────────────────────┐
│  1. Load Registry                     │ ← "Which patient is active?"
│     (patient_context_registry.json)   │
└─────────────┬─────────────────────────┘
              ↓
┌───────────────────────────────────────┐
│  2. Analyze User Intent               │ ← LLM determines what user wants
│     (PatientContextAnalyzer)          │    "Review patient_4" = NEW
│                                       │    "Switch to patient_15" = SWITCH
│                                       │    "What's the diagnosis?" = UNCHANGED
└─────────────┬─────────────────────────┘
              ↓
┌───────────────────────────────────────┐
│  3. Apply Decision                    │ ← Update registry, load history
│     (PatientContextService)           │
└─────────────┬─────────────────────────┘
              ↓
┌───────────────────────────────────────┐
│  4. Load Patient-Specific History     │ ← Get isolated history
│     (patient_4_context.json)          │
└─────────────┬─────────────────────────┘
              ↓
┌───────────────────────────────────────┐
│  5. Inject Fresh Snapshot             │ ← Add system message
│     "PATIENT_CONTEXT_JSON: {...}"     │    (agents see this)
│     (EPHEMERAL - never saved)         │
└─────────────┬─────────────────────────┘
              ↓
┌───────────────────────────────────────┐
│  6. Group Chat Orchestration          │ ← Agents process with context
│     (Agents see snapshot + history)   │
└─────────────┬─────────────────────────┘
              ↓
┌───────────────────────────────────────┐
│  7. Save History                      │ ← Snapshot is filtered out
│     (only real messages saved)        │
└───────────────────────────────────────┘
```

### Storage Structure

```
conversation_abc123/
├── session_context.json              ← Messages before any patient mentioned
├── patient_patient_4_context.json    ← patient_4's isolated history
├── patient_patient_15_context.json   ← patient_15's isolated history
└── patient_context_registry.json     ← SOURCE OF TRUTH
    {
      "active_patient_id": "patient_4",
      "patient_registry": {
        "patient_4": { "created_at": "...", "updated_at": "..." },
        "patient_15": { "created_at": "...", "updated_at": "..." }
      }
    }
```

---

## New Components

### 1. PatientContextAnalyzer

**File:** `src/services/patient_context_analyzer.py`

**What it does:** Uses an LLM to automatically detect what the user wants to do with patient context.

**Before:**
```python
# No automatic detection - had to manually parse or hardcode
if "patient" in message:
    # Do something... but what?
```

**After:**
```python
# LLM analyzes the message and returns structured decision
decision = await analyzer.analyze_patient_context(
    user_text="review patient_4",
    prior_patient_id=None,
    known_patient_ids=[]
)
# Returns: PatientContextDecision(
#   action="ACTIVATE_NEW",
#   patient_id="patient_4",
#   reasoning="User explicitly requests patient_4"
# )
```

**Examples:**

| User Input | Current Patient | Decision | Explanation |
|------------|----------------|----------|-------------|
| `"review patient_4"` | None | `ACTIVATE_NEW` | Start working on patient_4 |
| `"switch to patient_15"` | patient_4 | `SWITCH_EXISTING` | Change to patient_15 |
| `"what's the diagnosis?"` | patient_4 | `UNCHANGED` | Continue with patient_4 |
| `"clear patient"` | patient_4 | `CLEAR` | Reset everything |

**Key Features:**
- ✅ Automatic detection (no manual parsing)
- ✅ Considers current state
- ✅ Structured output (reliable format)
- ✅ Efficiency: skips LLM for short messages like "ok" or "yes"

---

### 2. PatientContextService

**File:** `src/services/patient_context_service.py`

**What it does:** Orchestrates the entire patient context lifecycle - deciding what to do and making it happen.

**Before:**
```python
# Logic was scattered across multiple files
# No central place handling patient context
```

**After:**
```python
# One method handles everything
decision, timing = await service.decide_and_apply(
    user_text="switch to patient_15",
    chat_ctx=chat_context
)
# Service handles:
# - Loading registry
# - Calling analyzer
# - Validating decision
# - Updating registry
# - Resetting kernel (if switching)
```

**Decision Flow:**

```
User says: "switch to patient_15"
    ↓
1. Load registry → "patient_4 is active"
    ↓
2. Ask analyzer → "SWITCH_EXISTING to patient_15"
    ↓
3. Validate → "patient_15 matches pattern, exists in registry"
    ↓
4. Apply:
   - Update registry: active = patient_15
   - Reset kernel (prevents cross-contamination)
   - Return decision: "SWITCH_EXISTING"
```

**Service Decisions:**

| Decision | Meaning |
|----------|---------|
| `NONE` | No patient context needed |
| `UNCHANGED` | Keep current patient active |
| `NEW_BLANK` | Activate a new patient (first time) |
| `SWITCH_EXISTING` | Switch to a known patient |
| `CLEAR` | Archive everything and reset |
| `RESTORED_FROM_STORAGE` | Silently reactivated from registry |
| `NEEDS_PATIENT_ID` | User intent unclear, need valid ID |

---

### 3. PatientContextRegistry Accessor

**File:** `src/data_models/patient_context_registry_accessor.py`

**What it does:** Manages the **source of truth** file that tracks which patient is active and which patients exist.

**Registry File Structure:**

```json
{
  "active_patient_id": "patient_4",
  "patient_registry": {
    "patient_4": {
      "patient_id": "patient_4",
      "facts": {},
      "created_at": "2025-09-30T16:30:00.000Z",
      "updated_at": "2025-09-30T16:45:00.000Z"
    },
    "patient_15": {
      "patient_id": "patient_15",
      "facts": {},
      "created_at": "2025-09-30T16:32:00.000Z",
      "updated_at": "2025-09-30T16:40:00.000Z"
    }
  }
}
```

**Why this exists:**
- ✅ Single source of truth for "which patient is active"
- ✅ Tracks all patients in the session (roster)
- ✅ Supports future features (facts, metadata)
- ✅ Clean archival during clear operations

---

### 4. Data Models

**File:** `src/data_models/patient_context_models.py`

**What it does:** Type-safe models for all patient context operations.

**Key Models:**

```python
# Represents a patient's context
class PatientContext:
    patient_id: str
    facts: dict = {}
    created_at: datetime
    updated_at: datetime

# LLM's structured decision
class PatientContextDecision:
    action: str  # "NONE" | "ACTIVATE_NEW" | "SWITCH_EXISTING" | ...
    patient_id: Optional[str]
    reasoning: str

# Performance tracking
class TimingInfo:
    analyzer_ms: float
    service_total_ms: float
```

---

## Modified Components

### 1. ChatContext (Data Model)

**File:** `src/data_models/chat_context.py`

**What changed:** Added fields to track active patient and multi-patient roster.

**Before:**
```python
class ChatContext:
    conversation_id: str
    chat_history: ChatHistory
    patient_id: str = None  # ❌ Existed but never used
```

**After:**
```python
class ChatContext:
    conversation_id: str
    chat_history: ChatHistory
    patient_id: str = None  # ✅ NOW USED: Points to active patient
    patient_contexts: Dict[str, PatientContext] = {}  # ✅ NEW: Roster of all patients
```

**Example:**

```python
# Turn 1: Mention patient_4
chat_ctx.patient_id = "patient_4"
chat_ctx.patient_contexts = {
    "patient_4": PatientContext(...)
}

# Turn 5: Switch to patient_15
chat_ctx.patient_id = "patient_15"
chat_ctx.patient_contexts = {
    "patient_4": PatientContext(...),
    "patient_15": PatientContext(...)
}
```

---

### 2. ChatContextAccessor (Storage Layer)

**File:** `src/data_models/chat_context_accessor.py`

**What changed:** 
1. Routes to different files based on patient
2. Filters out ephemeral snapshots when saving

#### Change 1: File Routing

**Before:**
```python
def get_blob_path(self, conversation_id: str) -> str:
    # ❌ Always the same file
    return f"{conversation_id}/chat_context.json"
```

**After:**
```python
def get_blob_path(self, conversation_id: str, patient_id: str = None) -> str:
    # ✅ Different file per patient
    if patient_id:
        return f"{conversation_id}/patient_{patient_id}_context.json"
    return f"{conversation_id}/session_context.json"
```

**Result:**

```
BEFORE:
conversation_123/
  └── chat_context.json  ← Everything mixed together

AFTER:
conversation_123/
  ├── session_context.json           ← Pre-patient messages
  ├── patient_patient_4_context.json ← Isolated history
  └── patient_patient_15_context.json← Isolated history
```

#### Change 2: Snapshot Filtering (CRITICAL)

**Before:**
```python
def serialize(chat_ctx: ChatContext) -> str:
    # ❌ Saves everything including snapshots
    return json.dumps({
        "chat_history": chat_ctx.chat_history.serialize()
    })
```

**After:**
```python
def serialize(chat_ctx: ChatContext) -> str:
    chat_messages = []
    
    for msg in chat_ctx.chat_history.messages:
        content = extract_content(msg)
        
        # ✅ CRITICAL: Filter out ephemeral snapshots
        if msg.role == AuthorRole.SYSTEM and content.startswith("PATIENT_CONTEXT_JSON"):
            continue  # Don't save this - it's ephemeral
        
        chat_messages.append({...})
    
    return json.dumps({"chat_history": chat_messages})
```

**Why this is critical:**

```python
# What agents see in memory:
[
    SYSTEM: "PATIENT_CONTEXT_JSON: {...}",  ← Ephemeral snapshot
    USER: "review patient_4",
    ASSISTANT: "Here's the plan..."
]

# What gets saved to disk:
[
    USER: "review patient_4",              ← Snapshot filtered out!
    ASSISTANT: "Here's the plan..."
]
```

**Benefits:**
- ✅ Snapshot is **never** persisted
- ✅ Registry is always the source of truth
- ✅ Fresh snapshot generated every turn
- ✅ No stale data

---

### 3. Healthcare Agents

**File:** `src/healthcare_agents/agent.py`

**What changed:** Message structure to enable consistent filtering.

**Before:**
```python
# ❌ Content was just a string
response_message = ChatMessageContent(
    role=AuthorRole.ASSISTANT,
    name=agent.name,
    content=response_text
)
```

**After:**
```python
# ✅ Content is structured with items
response_message = ChatMessageContent(
    role=AuthorRole.ASSISTANT,
    name=agent.name,
    items=[TextContent(text=response_text)]
)
```

**Why:** Accessor needs consistent structure to reliably filter snapshots.

---

### 4. Group Chat Orchestration

**File:** `src/group_chat.py`

**What changed:** Added confirmation gate and termination overrides for stability.

#### Change 1: Confirmation Gate

**The Problem:**
```
User: "review patient_4"
Orchestrator: "Plan: 1. PatientHistory, 2. Radiology..."
PatientHistory: [immediately starts executing] ❌ No user confirmation!
```

**The Solution:**
```python
# Added to selection prompt:
"""
CONFIRMATION GATE: If the most recent message is from Orchestrator
and contains a multi-step plan, WAIT for user confirmation.
Do not proceed to other agents yet.
"""
```

**Now it works:**
```
User: "review patient_4"
Orchestrator: "Plan: 1. PatientHistory, 2. Radiology... Good?"
[🛑 GATE: Wait for user]
User: "yes"
PatientHistory: [now executes] ✅
```

#### Change 2: Termination Overrides

**The Problem:**
```
Orchestrator: "PATIENT_CONTEXT_JSON: {...}"
LLM: "This looks like a conclusion" ❌ False termination!
```

**The Solution:**
```python
def evaluate_termination(result):
    last_text = extract_last_message_text(chat_ctx)
    
    # ✅ Override 1: Ignore snapshots
    if last_text.lower().startswith("patient_context_json"):
        return False  # Don't terminate
    
    # ✅ Override 2: Ignore handoffs
    if "back to you" in last_text.lower():
        return False  # Don't terminate
    
    # Fall back to LLM evaluation
    return llm_verdict()
```

**Benefits:**
- ✅ System messages don't end conversation
- ✅ Agent handoffs continue smoothly
- ✅ More reliable orchestration

---

### 5. Entry Points (Bot & API)

**Files:** `src/bots/assistant_bot.py`, `src/routes/api/chats.py`

**What changed:** Both entry points now follow the same pattern for patient context.

**Before:**
```python
async def on_message_activity(turn_context):
    # ❌ Simple, no patient awareness
    chat_ctx = await accessor.read(conversation_id)
    chat_ctx.chat_history.add_user_message(user_text)
    await process_chat(chat, chat_ctx)
    await accessor.write(chat_ctx)
```

**After:**
```python
async def on_message_activity(turn_context):
    # STEP 1: Load session context
    chat_ctx = await accessor.read(conversation_id, None)
    
    # STEP 2: Check for clear command
    if await handle_clear_command(user_text, chat_ctx):
        return  # Archives everything
    
    # STEP 3: ✅ NEW: Patient context decision
    decision, timing = await patient_service.decide_and_apply(
        user_text, chat_ctx
    )
    
    # STEP 4: ✅ NEW: Handle error cases
    if decision == "NEEDS_PATIENT_ID":
        await send_error("I need a valid patient ID")
        return
    
    # STEP 5: ✅ NEW: Load patient-specific history
    if chat_ctx.patient_id:
        isolated = await accessor.read(conversation_id, chat_ctx.patient_id)
        if isolated:
            chat_ctx.chat_history = isolated.chat_history
    
    # STEP 6: ✅ NEW: Inject fresh ephemeral snapshot
    snapshot = create_snapshot(chat_ctx)
    chat_ctx.chat_history.messages.insert(0, snapshot)
    
    # STEP 7: Add user message and process
    chat_ctx.chat_history.add_user_message(user_text)
    await process_chat(chat, chat_ctx)
    
    # STEP 8: Save (snapshot auto-filtered by accessor)
    await accessor.write(chat_ctx)
```

**Key Additions:**
1. ✅ Patient context service integration
2. ✅ Enhanced clear command (bulk archive)
3. ✅ Isolated history loading
4. ✅ Ephemeral snapshot injection
5. ✅ Error handling for invalid IDs

---

## Step-by-Step Turn Flow

### Scenario: User Discusses Two Patients

This example shows a complete conversation where the user works with two different patients.

---

#### **Turn 1: First time mentioning patient_4**

**User types:** `"review patient_4 labs"`

**What happens:**

```
1. Load session file
   Result: Empty (brand new conversation)

2. Check if user said "clear"
   Result: No

3. Patient context decision
   • Load registry → No registry file exists yet
   • Ask analyzer: What does user want?
     Analyzer says: "ACTIVATE_NEW patient_4"
   • Validate: "patient_4" matches our pattern ✅
   • Decision: NEW_BLANK (create new patient)
   • Action: 
     - Create a PatientContext for patient_4
     - Write registry file with patient_4 as active

4. Load patient_4's history file
   Result: Doesn't exist yet (first time) → Use empty history

5. Create and inject snapshot
   Add to position [0]: SYSTEM: "PATIENT_CONTEXT_JSON: {patient_id: 'patient_4'}"
   This tells agents: "You're working on patient_4"

6. Add user's message
   [1] USER: "review patient_4 labs"

7. Agents respond
   [2] ASSISTANT: "Plan: 1. PatientHistory will load labs..."

8. Save everything
   • Snapshot is automatically filtered out
   • Only save: [USER message, ASSISTANT message]
   • File: patient_patient_4_context.json
```

**Storage after Turn 1:**
```
conversation_abc123/
├── patient_patient_4_context.json ← Created with 2 messages
└── patient_context_registry.json  ← Created
    {
      "active_patient_id": "patient_4",
      "patient_registry": {
        "patient_4": {...}
      }
    }
```

---

#### **Turn 2: Continuing with patient_4**

**User types:** `"yes proceed"`

**What happens:**

```
1. Load session file
   Result: Empty (still no session-level messages)

2. Check if user said "clear"
   Result: No

3. Patient context decision
   • Load registry → patient_4 is currently active
   • Ask analyzer: What does user want?
     Message is short ("yes proceed")
     Heuristic: Skip analyzer, assume UNCHANGED
   • Decision: UNCHANGED (keep patient_4)

4. Load patient_4's history file
   Result: Contains 2 messages from Turn 1:
   [0] USER: "review patient_4 labs"
   [1] ASSISTANT: "Plan: ..."

5. Create and inject fresh snapshot
   Add to position [0]: SYSTEM: "PATIENT_CONTEXT_JSON: {patient_id: 'patient_4'}"
   Now history looks like:
   [0] SYSTEM: snapshot
   [1] USER: "review patient_4 labs"
   [2] ASSISTANT: "Plan: ..."

6. Add user's new message
   [3] USER: "yes proceed"

7. Agents respond
   PatientHistory: "Here are patient_4's labs... Back to you Orchestrator."
   [Termination check: Sees "back to you" → Continue, don't stop]
   Orchestrator: "Labs received. Moving to next step..."

8. Save everything
   • Snapshot is automatically filtered out
   • Save: [4 messages total now]
```

---

#### **Turn 3: Switching to a different patient**

**User types:** `"switch to patient_15"`

**What happens:**

```
1. Load session file
   Result: Empty

2. Check if user said "clear"
   Result: No

3. Patient context decision
   • Load registry → patient_4 is currently active
   • Ask analyzer: What does user want?
     Analyzer says: "ACTIVATE_NEW patient_15"
   • Validate: "patient_15" matches pattern, NOT in registry yet
   • Decision: NEW_BLANK (create new patient)
   • Action:
     - Create PatientContext for patient_15
     - Update registry: active = patient_15
     - ⚠️ RESET KERNEL (clear analyzer's memory to prevent patient_4 data leaking)
     - Write updated registry

4. Load patient_15's history file
   Result: Doesn't exist → Use empty history
   (patient_4's history remains untouched in its own file)

5. Create and inject fresh snapshot
   Add to position [0]: SYSTEM: "PATIENT_CONTEXT_JSON: {
     patient_id: 'patient_15',
     all_patient_ids: ['patient_4', 'patient_15']
   }"
   Shows agents: "Now working on patient_15, patient_4 still exists"

6. Add user's message
   [1] USER: "switch to patient_15"

7. Agents respond
   [2] ASSISTANT: "Switched to patient_15. What would you like to review?"

8. Save everything
   • Snapshot filtered out
   • Save to: patient_patient_15_context.json (NEW FILE)
```

**Storage after Turn 3:**
```
conversation_abc123/
├── patient_patient_4_context.json  ← Still has patient_4's history (4 messages)
├── patient_patient_15_context.json ← NEW: patient_15's history (2 messages)
└── patient_context_registry.json   ← Updated
    {
      "active_patient_id": "patient_15",  ← Changed from patient_4
      "patient_registry": {
        "patient_4": {...},
        "patient_15": {...}  ← Added
      }
    }
```

**Key Point:** patient_4's history is completely isolated and unchanged!

---

#### **Turn 4: Clearing everything**

**User types:** `"clear patient context"`

**What happens:**

```
1. Load session file
   Result: Empty

2. Check if user said "clear"
   Result: YES ✅

3. Clear command handler runs
   • Find all files:
     - patient_patient_4_context.json
     - patient_patient_15_context.json
     - patient_context_registry.json
   
   • Create archive folder: archive/20250930T164500/
   
   • Copy each file to archive with timestamp:
     archive/20250930T164500/conversation_abc123/
       ├── 20250930T164500_patient_patient_4_archived.json
       ├── 20250930T164500_patient_patient_15_archived.json
       └── 20250930T164500_patient_context_registry_archived.json
   
   • Delete original files
   
   • Reset in-memory state:
     - chat_ctx.patient_id = None
     - chat_ctx.patient_contexts = {}
   
   • Send message: "Patient context cleared"

4-8. Skipped (already returned after clear)
```

**Storage after Turn 4:**
```
conversation_abc123/
└── archive/
    └── 20250930T164500/
        └── conversation_abc123/
            ├── 20250930T164500_patient_patient_4_archived.json
            ├── 20250930T164500_patient_patient_15_archived.json
            └── 20250930T164500_patient_context_registry_archived.json
```

**Result:** Clean slate! Ready for new patients.

---

### Visual Summary

```
Turn 1: "review patient_4"
  → Create patient_4 ✅
  → patient_4_context.json created
  → Registry: active = patient_4

Turn 2: "yes proceed"
  → Continue with patient_4 ✅
  → patient_4_context.json updated (more messages)
  → Registry: active = patient_4 (unchanged)

Turn 3: "switch to patient_15"
  → Create patient_15 ✅
  → patient_15_context.json created
  → patient_4_context.json untouched
  → Registry: active = patient_15

Turn 4: "clear patient context"
  → Archive all files ✅
  → Delete originals
  → Ready for fresh start
```

---

## Configuration

### Customizing Patient ID Pattern

By default, the system accepts IDs like `patient_4`, `patient_15`, etc.

You can customize this via environment variable:

```bash
# Default pattern
export PATIENT_ID_PATTERN="^patient_[0-9]+$"

# Medical Record Number format
export PATIENT_ID_PATTERN="^MRN[0-9]{7}$"
# Accepts: MRN1234567

# Multiple formats
export PATIENT_ID_PATTERN="^(patient_[0-9]+|MRN[0-9]{7})$"
# Accepts: patient_4 OR MRN1234567
```

> [!IMPORTANT]
> If you change the pattern, update the analyzer prompt in `patient_context_analyzer.py` to match.

---

## Key Concepts Explained

### What is "Ephemeral Snapshot"?

**Simple explanation:** A temporary system message that tells agents about the current patient. It's generated fresh every turn and **never saved**.

```python
# Generated every turn:
snapshot = {
    "patient_id": "patient_4",
    "all_patient_ids": ["patient_4", "patient_15"],
    "generated_at": "2025-09-30T16:45:00Z"
}

# Injected as message:
SYSTEM: "PATIENT_CONTEXT_JSON: {snapshot}"

# Agents see this and know: "I'm working on patient_4"

# When saving: This message is filtered out (never persisted)
```

### What is "Kernel Reset"?

**Simple explanation:** When switching patients, the analyzer's AI is reset to prevent mixing patient data.

```python
# Without reset:
User: "review patient_4"
Analyzer: [builds understanding of patient_4]
User: "switch to patient_15"
Analyzer: [still has patient_4 context in memory] ❌

# With reset:
User: "review patient_4"
Analyzer: [builds understanding of patient_4]
User: "switch to patient_15"
Service: kernel.reset()  # Clears analyzer memory
Analyzer: [fresh start for patient_15] ✅
```

### What is "Registry as Source of Truth"?

**Simple explanation:** The registry file always has the correct answer for "which patient is active".

```python
# Registry file:
{ "active_patient_id": "patient_4" }

# When loading:
1. Read registry → "patient_4 is active"
2. Load patient_4_context.json
3. Generate fresh snapshot from registry
4. Inject snapshot

# Benefits:
- No stale snapshots
- Always accurate
- Single source of truth
```

---

## Summary

**What you need to remember:**

1. **Each patient gets their own history file** - Complete isolation
2. **Registry tracks which patient is active** - Single source of truth
3. **LLM automatically detects patient intent** - No manual parsing
4. **Fresh snapshot injected every turn** - Never persisted
5. **Agents see current patient context** - Grounded responses
6. **Safe switching with kernel reset** - No cross-contamination
7. **Bulk archival on clear** - Organized and complete

**The result:** You can work on multiple patients in one conversation, switch between them seamlessly, and the system keeps everything organized and isolated.

---

**Last Updated:** October 1, 2025  
**Status:** Production-ready (`sekar/pc_poc` branch)