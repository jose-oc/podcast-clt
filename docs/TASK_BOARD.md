# Task Board & Progress Tracker

This board tracks the implementation status of all `podcast-ctl` work packages.

| Task ID | Work Package | Status | Spec / Prompt File | Output Tests |
| :--- | :--- | :--- | :--- | :--- |
| **Task 1** | Scaffolding & Rich UI Console | ✅ Completed | `docs/subagent_tasks/task_1_scaffolding_ui.md` | `tests/test_console.py` |
| **Task 2** | Domain Models & SQLite Knowledge Store | ✅ Completed | `docs/subagent_tasks/task_2_models_storage.md` | `tests/test_storage.py` |
| **Task 3** | Discovery & Ingestion Engine | ✅ Completed | `docs/subagent_tasks/task_3_discovery_ingestion.md` | `tests/test_discovery.py` |
| **Task 4** | Transcription Engines & Dispatcher | ✅ Completed | `docs/subagent_tasks/task_4_transcription_engines.md` | `tests/test_engines.py` |
| **Task 5** | Pre-Flight Gatekeeper & Interactive Learning | ✅ Completed | `docs/subagent_tasks/task_5_gatekeeper_learning.md` | `tests/test_gatekeeper.py` |
| **Task 6** | Multi-Format Exporters | ✅ Completed | `docs/subagent_tasks/task_6_exporters.md` | `tests/test_exporters.py` |
| **Task 7** | CLI Commands, Docs & Integration | ✅ Completed | `docs/subagent_tasks/task_7_cli_orchestration.md` | `tests/test_cli.py` |
| **Phase 2a/2b** | Knowledge Base: derived Markdown, INDEX.md, FTS5 chunk search | ✅ Completed | `docs/KNOWLEDGE_BASE_DESIGN.md` → `docs/KNOWLEDGE_BASE.md` | `tests/test_kb.py` |
| **Phase 2c** | KB vector embeddings (local default, optional cloud adapters) + hybrid fusion | ⬜ Pending | `docs/KNOWLEDGE_BASE_DESIGN.md` | — |
| **Phase 2d** | KB golden-query evaluation harness | ⬜ Pending | `docs/KNOWLEDGE_BASE_DESIGN.md` | — |

---

## Dependency Graph & Concurrency

```
[Task 1: Scaffolding & UI]
         │
         ▼
[Task 2: Models & SQLite Store]
         ├──► [Task 3: Discovery & Ingestion] ─────────┐
         │                                              ▼
         ├──► [Task 4: Transcription Engines] ──► [Task 5: Gatekeeper]
         │                                              │
         ├──► [Task 6: Exporters] ─────────────────────┤
                                                        ▼
                                              [Task 7: CLI & Docs]
```

* **Phase A:** Task 1 $\rightarrow$ Task 2 (Foundational schemas & DB)
* **Phase B (Parallel):** Task 3 (Discovery), Task 4 (Engines), Task 6 (Exporters)
* **Phase C:** Task 5 (Gatekeeper & Learning)
* **Phase D:** Task 7 (CLI Orchestrator, Docs, Final Verification)
