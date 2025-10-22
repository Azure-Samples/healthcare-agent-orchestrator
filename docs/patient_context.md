# Patient Context Management

The Healthcare Agent Orchestrator uses an ephemeral, registry‑backed model to maintain isolated conversational state per patient inside a single conversation. This document explains the current implementation, how patient IDs are detected and validated, and how the system persists, restores, and clears patient context safely.

> [!IMPORTANT]
> `PATIENT_CONTEXT_JSON` system snapshot messages are ephemeral. They are injected each turn and never persisted. The registry is the single source of truth for the active patient and roster.

## Core Objectives

| Objective | Mechanism |
|-----------|-----------|
| Patient isolation | Separate per‑patient history files (`patient_{id}_context.json`) |
| Multi‑patient roster | Central registry file (`patient_context_registry.json`) |
| Ephemeral grounding | Fresh `PATIENT_CONTEXT_JSON` snapshot every turn (index 0) |
| Low‑noise storage | Snapshots stripped before persistence |
| Safe switching & activation | LLM analyzer + service validation + kernel reset on change |
| Complete clear/reset | Archives session, all patient histories, and registry in timestamped folder |

## High‑Level Turn Flow

1. Load session `ChatContext` (no patient file yet).
2. Check for clear command (archive + reset if present).
3. Run `PatientContextService.decide_and_apply()`:
   - Hydrate registry into `chat_ctx.patient_contexts`.
   - Attempt silent restore if no active patient.
   - Invoke analyzer (unless short-message heuristic skip).
   - Apply decision (activate / switch / clear / none).
4. If patient active: load that patient’s stored history into memory.
5. Strip any previous `PATIENT_CONTEXT_JSON` system snapshot(s).
6. Inject a new snapshot (ephemeral).
7. Append user message.
8. Run multi-agent orchestration (selection + termination).
9. (Teams) Append single guarded `PT_CTX` audit footer.
10. Persist updated history (patient-specific if active else session).
11. Registry already reflects new active pointer (if changed).

> [!NOTE]
> Only one snapshot should exist in memory at any time. The system enforces this by stripping before reinjection.

## Decision Engine (PatientContextAnalyzer)

Structured LLM classifier producing `PatientContextDecision (action, patient_id?, reasoning)`.

| Action | Meaning |
|--------|---------|
| `NONE` | General / meta turn (no context change) |
| `ACTIVATE_NEW` | Activate a new patient (ID extracted) |
| `SWITCH_EXISTING` | Switch to known patient |
| `UNCHANGED` | Keep current active patient |
| `CLEAR` | User intent to wipe contexts |
| (Service) `RESTORED_FROM_STORAGE` | Silent revival of last active from registry |
| (Service) `NEEDS_PATIENT_ID` | User intended change but no valid ID provided |

Service may reinterpret `ACTIVATE_NEW` as `NEW_BLANK` (new record).

### Patient ID Detection

| Stage | Logic |
|-------|-------|
| Heuristic Skip | Short (≤ 15 chars) and no `patient|clear|switch` → bypass analyzer |
| LLM Extraction | Analyzer only returns `patient_id` for `ACTIVATE_NEW` / `SWITCH_EXISTING` |
| Regex Validation | Must match `^patient_[0-9]+$` (`PATIENT_ID_PATTERN`) |
| New vs Existing | In registry → switch; not in registry → new blank context |
| Invalid / Missing | Activation intent without valid pattern → `NEEDS_PATIENT_ID` |
| Silent Restore | Action `NONE` + no active + registry has prior active → restore |
| Isolation Reset | Patient change triggers `analyzer.reset_kernel()` |

**Examples**

| User Input | Analyzer Action | Service Decision | Notes |
|------------|-----------------|------------------|-------|
| `start review for patient_4` | `ACTIVATE_NEW` | `NEW_BLANK` | New patient |
| `switch to patient_4` | `SWITCH_EXISTING` | `SWITCH_EXISTING` | Already known |
| `patient_4` | `SWITCH_EXISTING` | `SWITCH_EXISTING` | Minimal intent |
| `switch patient please` | `ACTIVATE_NEW` | `NEEDS_PATIENT_ID` | Missing ID |
| `clear patient` | `CLEAR` | `CLEAR` | Full reset |
| `ok` | (Skipped) | `UNCHANGED` or restore | Too short for analysis |

> [!TIP]
> To support additional formats (e.g., MRN), update `PATIENT_ID_PATTERN` and adjust the analyzer prompt description.

### Customizing Patient ID Format

The system validates patient IDs using a configurable regex pattern.

**Default Pattern:** `^patient_[0-9]+$` (e.g., `patient_4`, `patient_123`)

**To Use a Different Format:**

Set the `PATIENT_ID_PATTERN` environment variable before starting the application:

```bash
# Example: Accept MRN format
export PATIENT_ID_PATTERN="^mrn-[A-Z0-9]{6}$"

# Example: Accept multiple formats (either patient_N or mrn-XXXXXX)
export PATIENT_ID_PATTERN="^(patient_[0-9]+|mrn-[A-Z0-9]{6})$"

# Then start the app
python src/app.py
```

**Important:** When changing the pattern, ensure the analyzer prompt in `patient_context_analyzer.py` reflects the new format so the LLM extracts IDs correctly.

## Registry (Source of Truth)

`patient_context_registry.json` stores:
- `active_patient_id`
- `patient_registry` map of patient entries:
  - `patient_id`
  - `facts` (lightweight dict, extensible)
  - `conversation_id`
  - timestamps

No system snapshots or timing entries are stored here.

## Storage Layout

```
{conversation_id}/
├── session_context.json
├── patient_{patient_id}_context.json
├── patient_context_registry.json
└── archive/
    └── {timestamp}/
        ├── {conversation_id}/
        │   ├── {timestamp}_session_archived.json
        │   ├── {timestamp}_patient_patient_4_archived.json
        │   └── {timestamp}_patient_patient_15_archived.json
        └── {timestamp}_patient_context_registry_archived.json
```

> [!NOTE]
> Only dialogue and display/output arrays are persisted—never ephemeral snapshots.

## Ephemeral Snapshot

Format (in memory only, first message):

```text
PATIENT_CONTEXT_JSON: {"conversation_id":"uuid","patient_id":"patient_16","all_patient_ids":["patient_4","patient_15","patient_16"],"generated_at":"2025-09-30T16:32:11.019Z"}
```

## Runtime Data Model

```python
ChatContext:
  conversation_id: str
  patient_id: Optional[str]
  patient_contexts: Dict[str, PatientContext]
  chat_history: ChatHistory
```

Hydration each turn:

```python
await patient_context_service._ensure_patient_contexts_from_registry(chat_ctx)
```

## Isolation & Transitions

| Operation | Result |
|-----------|--------|
| New patient | Kernel reset + new context file |
| Switch patient | Kernel reset + load patient history |
| Clear | Archive all + wipe memory state |
| Restore | Silent reactivation from registry pointer |
| General turn | Session-only if no active patient |

## Short-Message Heuristic

Skip analyzer when:
- Length ≤ 15
- No key substrings (`patient`, `clear`, `switch`)

Outcomes:
- Active patient → `UNCHANGED`
- None → attempt restore → `RESTORED_FROM_STORAGE` or `NONE`

## PatientContextService Responsibilities

- Hydrate registry → memory each invocation.
- Attempt restoration if no active.
- Run analyzer (unless skipped).
- Apply decision + side effects:
  - Activation / switch → registry update, optional kernel reset
  - Clear → archive + wipe
- Return `(decision, TimingInfo)`.
- Never inject snapshot (caller handles ephemeral injection).

Decision union:
```
"NONE" | "UNCHANGED" | "NEW_BLANK" | "SWITCH_EXISTING" |
"CLEAR" | "RESTORED_FROM_STORAGE" | "NEEDS_PATIENT_ID"
```


## Example Turn (Persisted vs In-Memory)

In memory:

```
[System] PATIENT_CONTEXT_JSON: {...}
[User] Start review for patient_4
[Assistant:Orchestrator] Plan...
```

Persisted (`patient_4_context.json`):

```json
{
  "conversation_id": "c123",
  "patient_id": "patient_4",
  "chat_history": [
    {"role": "user", "content": "Start review for patient_4"},
    {"role": "assistant", "name": "Orchestrator", "content": "Plan..."}
  ]
}
```

Snapshot intentionally absent.

## Clear Operation

Triggers on:
```
clear | clear patient | clear context | clear patient context
```

Procedure:
1. Archive (session, each patient file, registry).
2. Reset in-memory context + histories.
3. Persist empty session context.
4. Respond with confirmation.

## Roster & Meta Queries

Agents derive:
- Active patient → `patient_id`
- Roster → `all_patient_ids` (sorted)

Rules:
- No hallucinated IDs.
- Avoid redundant re-planning for same active patient mention.

## Code Reference (Filtering & Injection)

```python
# Strip prior snapshot(s)
chat_ctx.chat_history.messages = [
    m for m in chat_ctx.chat_history.messages
    if not (
        m.role == AuthorRole.SYSTEM
        and getattr(m, "items", None)
        and m.items
        and getattr(m.items[0], "text", "").startswith(PATIENT_CONTEXT_PREFIX)
    )
]

snapshot = {
    "conversation_id": chat_ctx.conversation_id,
    "patient_id": chat_ctx.patient_id,
    "all_patient_ids": sorted(chat_ctx.patient_contexts.keys()),
    "generated_at": datetime.utcnow().isoformat() + "Z",
}

line = f"{PATIENT_CONTEXT_PREFIX}: {json.dumps(snapshot, separators=(',', ':'))}"
sys_msg = ChatMessageContent(role=AuthorRole.SYSTEM, items=[TextContent(text=line)])
chat_ctx.chat_history.messages.insert(0, sys_msg)
```


