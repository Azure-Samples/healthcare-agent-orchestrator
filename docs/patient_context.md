# Patient Context Management (Current Architecture)

This document describes the current (ephemeral, registry‑based) patient context model. It replaces any legacy behavior that persisted system snapshot messages or embedded timing metadata in `PATIENT_CONTEXT_JSON`.

---

## ✅ Core Goals

| Goal | Current Mechanism |
|------|-------------------|
| Patient isolation | Separate per‑patient history blobs: `patient_{id}_context.json` |
| Multi-patient roster | Central registry: `patient_context_registry.json` (authoritative) |
| Ephemeral grounding | Fresh `PATIENT_CONTEXT_JSON` system snapshot injected each turn (never persisted) |
| Low-noise storage | Only user + agent dialogue retained; snapshots stripped before write |
| Safe switching | Analyzer governs transitions; kernel reset only when changing active patient |
| Clear operation | Archives session + all patient histories + registry, then resets in-memory state |

---

## 🔄 High‑Level Turn Flow

1. Load the session `ChatContext` (no patient file loaded yet).
2. If a clear command was issued: archive everything, reset state, send “cleared” reply, stop.
3. Call `PatientContextService.decide_and_apply()`:
   - Hydrate `chat_ctx.patient_contexts` from the registry (source of truth).
   - Apply any transition: activate, switch, clear, restore, or no-op.
4. If a patient is now active, load that patient’s isolated chat history (replacing the session history in memory).
5. Remove any prior ephemeral `PATIENT_CONTEXT_JSON` system snapshot(s) from memory.
6. Construct and inject a fresh ephemeral snapshot system message (not persisted).
7. Append the raw user message.
8. Run multi-agent orchestration (Orchestrator + specialists).
9. (Teams only) Append a single guarded `PT_CTX` audit footer (never duplicates).
10. Persist:
    - Write to the patient file if `chat_ctx.patient_id` is set; otherwise to the session file.
    - The ephemeral snapshot is excluded (it was already filtered before persistence).
11. The registry already reflects any activation / switch / new patient from step 3.

---

## 🧠 Decision Engine (`PatientContextAnalyzer`)

Produces an action plus (optionally) a `patient_id`.

| Action | Meaning |
|--------|---------|
| `NONE` | No patient context required (general/meta turn) |
| `ACTIVATE_NEW` | Start a brand-new patient (ID extracted) |
| `SWITCH_EXISTING` | Switch to an existing (registry) patient |
| `UNCHANGED` | Keep the current active patient |
| `CLEAR` | User intends to clear all patient context |
| (Service-derived) `RESTORED_FROM_STORAGE` | Previous active patient resurrected (no active in-memory, registry had one) |
| (Service-derived) `NEEDS_PATIENT_ID` | User intent implies patient focus but no resolvable ID provided |

Service-level post-processing can reclassify into operational decisions like `NEW_BLANK`.

---

## 🏛 Registry (Single Source of Truth)

File: `patient_context_registry.json`

```json
{
  "conversation_id": "uuid",
  "active_patient_id": "patient_16",
  "patient_registry": {
    "patient_4": {
      "patient_id": "patient_4",
      "facts": {},
      "conversation_id": "uuid",
      "last_updated": "2025-09-28T14:55:41.221939+00:00"
    },
    "patient_16": {
      "patient_id": "patient_16",
      "facts": {},
      "conversation_id": "uuid",
      "last_updated": "2025-09-28T15:04:10.119003+00:00"
    }
  },
  "last_updated": "2025-09-28T15:04:10.119020+00:00"
}
```

Characteristics:
- Contains only roster + active pointer.
- No embedded system message text.
- `facts` is a lightweight dict (reserved for future enrichment).

---

## 🗂 Storage Layout

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

Key behavior:
- `PATIENT_CONTEXT_JSON` messages never persist.
- Only dialogue + ancillary arrays (display/output) remain.

---

## 💬 Ephemeral Snapshot Format

Injected each turn at index 0 of `chat_ctx.chat_history.messages`:

```text
PATIENT_CONTEXT_JSON: {"conversation_id":"uuid","patient_id":"patient_16","all_patient_ids":["patient_4","patient_15","patient_16"],"generated_at":"2025-09-28T15:07:44.012345Z"}
```

Differences vs legacy:

| Aspect | Legacy | Current |
|--------|--------|---------|
| Timing field (`timing_sec`) | Present | Removed |
| Injection site | Inside service | Caller (route / bot) post-decision |
| Persistence | Stored & reloaded | Rebuilt every turn (never stored) |
| Cleanup | Service replaced old | Caller strips before reinjecting |
| Purpose | Grounding (stale risk) | Always-fresh grounding snapshot |

Rationale for removal of timing: operational concern, not reasoning signal.

---

## 🧩 Runtime Data Model (Simplified)

```python
ChatContext:
  conversation_id: str
  patient_id: Optional[str]
  patient_contexts: Dict[str, PatientContext]  # Hydrated from registry each turn
  chat_history: Semantic Kernel chat history
```

Hydration snippet:

```python
await patient_context_service._ensure_patient_contexts_from_registry(chat_ctx)
# chat_ctx.patient_contexts = { pid: PatientContext(...), ... }
```

Only `patient_id` determines which file receives writes.

---

## 🔐 Isolation Semantics

| Operation | Effect |
|-----------|--------|
| Switch patient | Kernel reset + load that patient’s chat history into memory |
| New patient | Kernel reset + start empty history |
| Clear | Archive all (session, patients, registry) then wipe memory |
| General (no patient) | Session-only evolution; `patient_id` stays `None` |
| Restore (idle resume) | If no active but registry has a previous active → restore it |

---

## 🧪 Short-Message Heuristic

Skip analyzer if:
- Input length ≤ 15 chars AND
- Lacks substrings: `patient`, `clear`, `switch`

Outcomes:
- Active patient exists → treat as `UNCHANGED`
- None active → attempt restore → `RESTORED_FROM_STORAGE` or `NONE`

Purpose: Avoid unnecessary model calls on handoff fragments (e.g., “back to you”).

---

## 🛠 `PatientContextService` Responsibilities

Still does:
- Sync from registry each invocation.
- Run analyzer (unless heuristic skip).
- Perform transitions: new / switch / clear / restore.
- Reset kernel only on patient change.
- Update registry on activation/switch.

No longer does:
- Inject snapshot messages.
- Embed timing into snapshots.
- Persist patient metadata within chat histories.

Return signature (conceptually):
```
(decision: Decision, timing: TimingInfo)
```

Service-level decision literal union:
```
"NONE" | "UNCHANGED" | "NEW_BLANK" | "SWITCH_EXISTING" |
"CLEAR" | "RESTORED_FROM_STORAGE" | "NEEDS_PATIENT_ID"
```

---

## 🧵 Web vs Teams Parity

Shared pipeline:
1. Strip old snapshot(s).
2. Inject new snapshot (fresh `generated_at`).
3. Run group chat orchestration.
4. Persist history (snapshot excluded).
5. Snapshot grounds roster/meta reasoning.

Teams additions:
- Human-readable `PT_CTX` footer (single insertion via guard).
- Footer includes `Session ID:`.

Guard pattern:
```python
if all_pids and "PT_CTX:" not in response.content:
    # append audit footer once
```

---

## 📎 Example Turn

In-memory (transient):
```
[System] PATIENT_CONTEXT_JSON: {"conversation_id":"c123","patient_id":"patient_4","all_patient_ids":["patient_4"],"generated_at":"...Z"}
[User] Provide history
[Assistant:PatientHistory] Here is the complete patient data ...
```

Persisted (`patient_4_context.json`):
```json
{
  "conversation_id": "c123",
  "patient_id": "patient_4",
  "chat_history": [
    {"role": "user", "content": "Provide history"},
    {"role": "assistant", "name": "PatientHistory", "content": "Here is the complete patient data ..."}
  ],
  "patient_data": [],
  "display_blob_urls": [],
  "output_data": []
}
```

Snapshot absent by design.

---

## 🧽 Clear Operation

Triggers on any of:
```
"clear", "clear patient", "clear context", "clear patient context"
```

Steps:
1. Archive session file, all patient files (registry-sourced), registry file.
2. Reset: `patient_id = None`, `patient_contexts.clear()`, `chat_history.clear()`.
3. Persist fresh empty session context.
4. Reply with confirmation.

---

## 🧾 Roster & Meta Queries

Handled through Orchestrator prompt rules using the latest snapshot:
- Use `all_patient_ids` + `patient_id`.
- Never hallucinate absent patients.
- Don’t “re-plan” when user repeats the already-active patient.

Stability aids:
- Sort `all_patient_ids`.
- (Optional future) Add `patient_count` or `_hint` if reasoning degrades.

---

## 🛡 Why Ephemeral?

| Legacy Issue | Current Resolution |
|--------------|-------------------|
| Persisted stale roster | Snapshot rebuilt every turn from registry |
| Stacked duplicate system messages | Strip → reinject ensures exactly one |
| Timing noise in reasoning | Removed from snapshot |
| Confusion over authority | Registry authoritative; snapshot transient |
| Unnecessary analyzer calls | Heuristic bypass for trivial handoffs |

---

## 🧪 Validation Scenarios

| Scenario | Expected |
|----------|----------|
| First mention “start review for patient_4” | Decision = `NEW_BLANK`; snapshot shows only `patient_4` |
| Switch to existing other patient | Decision = `SWITCH_EXISTING`; kernel reset occurs |
| Redundant switch to same patient | Decision = `UNCHANGED`; no reset |
| Short handoff “back to you” | Analyzer skipped; `UNCHANGED` (if active) |
| Clear then new command | Clean slate → next patient command = new activation |
| Teams render | Single `PT_CTX` footer incl. Session ID |
| Persistence audit | No `PATIENT_CONTEXT_JSON` lines in stored files |

---

## 🛠 Code Reference (Filtering + Injection)

```python
# Remove old snapshot(s)
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

Teams footer guard (conceptual):
```python
if all_pids and "PT_CTX:" not in response.content:
    # append audit footer once
```

---

## 🔮 Future Enhancements (Optional)

| Idea | Rationale |
|------|-----------|
| Deterministic plan confirmation flag | Reduce reliance on prompt-only gating |
| Snapshot `patient_count` field | Faster meta answers (no length calc) |
| Registry `facts` enrichment | Richer grounding for specialized agents |
| Test harness for decision invariants | Prevent regression in edge transitions |
| LLM classification caching | Reduce analyzer calls for repeated short intents |

---

Last updated: 2025-09-28  
Status: Stable ephemeral model in production branch (`sekar/pc_poc`).
