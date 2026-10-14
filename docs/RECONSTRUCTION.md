# ETERNIX Reconstruction — Baseline, Defect Register & Capability Matrix

_Generated during forensic audit. Environment: Fedora, Python 3.14.8, 8 CPU / ~8 GB RAM, single Linux host._

## Phase 0 — Operational baseline (measured)

| Check | Result |
|---|---|
| Python / venv | `.venv` → Python 3.14.8 ✅ |
| `import eternix.api.server` | OK, 81 routes ✅ |
| `pytest` (tests/) | **56 passed** ✅ |
| Frontend build | Static assets present in `src/eternix/static/assets` ✅ (built) |
| Frontend deps | `frontend/node_modules` installed ✅ |
| llama.cpp source | `third_party/llama.cpp` @ v0.6.0 (d81235049) ✅ |
| llama.cpp **binaries** | **MISSING** (`build/llama.cpp/bin/{llama-cli,llama-server}` absent) ❌ |
| GGUF models | 6 present (~6 GB): qwen3-4b, qwen-coder-1.5b, qwen-vl-2b(+mmproj), qwen3-embedding-0.6b, qwen2.5-1.5b ✅ |
| Git state (before work) | **0 commits**, everything untracked ⚠️ → checkpoint commit created (92 files, no secrets/models) |
| Build toolchain | cmake 4.3.0, gcc 16.2.1, make, ninja 1.13.2, node 24.18, npm 11.16 ✅ |

## Architecture (as found)

- **Transport/API:** `src/eternix/api/server.py` — FastAPI, routes at root + `/api` aliases, SPA fallback, SSE objective events.
- **Auth/eligibility:** `src/eternix/auth/*` — mandatory onboarding state machine (register → verify → payment → active), backend-enforced gate `require_active_account` (valid token + active account + eligible payment). Dev sandbox provider.
- **Agent:** `src/eternix/core/orchestrator.py` (keyword planner + verifier + recovery) and `core/langgraph_orchestrator.py` (LLM-planned LangGraph). Server uses the LangGraph orchestrator.
- **Tools:** `src/eternix/tools/*` — real handlers for filesystem, command, coding (tree-sitter, ruff, pytest, git), document, data, web (ddgs/trafilatura), memory (qdrant), vision, audio, generation.
- **Persistence:** `src/eternix/core/task_store.py` (SQLAlchemy/SQLite: objectives, tasks, tool_results, conversations, messages, workspaces, capabilities, models) + `auth/store.py` (accounts/sessions/audit).
- **Inference:** `src/eternix/inference/llama_cpp.py` + `models/manager.py` — llama.cpp CLI/server adapters, role→model mapping, LRU model loading.
- **Frontend:** `frontend/src` — React chat-first workspace (AuthScreen → Sidebar + ChatArea), typed API client with token refresh.

## Defect register (updated)

| ID | Sev | Subsystem | Finding | Root cause | Status |
|---|---|---|---|---|---|
| DEF-001 | High | Local inference | Genuine local inference could not run — no llama.cpp binaries; agent LLM calls returned empty/error | `build/llama.cpp/bin` never built | **Fixed + Verified** (built llama.cpp v0.6.0; real "PONG" completion at 8.6 t/s; 6 models discovered) |
| DEF-005 | Critical | Filesystem/command/coding tools | **Sandbox escape:** `fs.*`/`coding.*`/`cmd.*` tools resolved paths against the server CWD with no confinement, so any authenticated user/agent could read/write/delete/move arbitrary host files while the API reported `success: True` | `_resolve_path` used `Path.cwd()`; no workspace containment | **Fixed + Verified** (all tools confined to active workspace; `TaskStore.get_active_workspace_path()`; symlink-safe canonicalization; 3 regression tests pass) |
| DEF-002 | Med | API honesty | `POST /intelligence/index` returned hardcoded `{"status":"ok","message":"indexed"}`; `GET /intelligence/status` returned `{"status":"idle"}` — no real work | Stub endpoints | **Fixed + Verified** (now truthfully report no background indexer; live search via coding.search) |
| DEF-003 | Low | API honesty | `GET /research/history` and `GET /artifacts` always returned `[]` | Stub endpoints | **Fixed + Verified** (truthful responses; artifacts now list completed task outputs per objective) |
| DEF-007 | Med | Inference runtime portability | llama.cpp binaries had a hardcoded build-tree RUNPATH (`third_party/llama.cpp/build/bin`), so a relocated/bundled runtime could not find its shared libs | Build-time RUNPATH | **Fixed** (`InferenceBackend._runtime_env()` prepends `llama_cpp_bin` to `LD_LIBRARY_PATH` for all spawned processes) |
| DEF-004 | Low | Persistence | SQLAlchemy SAWarning: `metadata` reserved attr on `AuditEventORM`/`EntitlementRecordORM` | Column named `metadata` | Open (cosmetic; touches many call sites — deferred, low risk) |
| DEF-006 | — | Command execution | `cmd.exec`/`cmd.bg_start` allowed arbitrary working directories | No cwd confinement | **Fixed** (folded into DEF-005 fix; cwd confined to workspace) |

## Verification evidence (this session)

| Check | Command | Result |
|---|---|---|
| Unit tests | `pytest tests/test_core.py tests/test_email_verification.py` | **57 passed** (incl. new DEF-005 regression) |
| E2E journey (live server, isolated DB) | `pytest tests/test_e2e_journey.py` | **8 passed** — auth gate (401/403), full onboarding, real tool exec, sandbox-escape blocked, conversation persistence, and a real LLM-planned objective (loads the local coding model, plans, executes `fs.list`, completes) |
| Lint | `ruff check src/eternix/tools/ ... tests/` | **All checks passed** |
| llama.cpp build | `cmake --build build -j2` | **Built** (llama-cli, llama-server, llama-mtmd-cli, exit 0) |
| Real inference | `llama-cli -m qwen2.5-1.5b ... "Reply PONG"` | **"PONG"** @ 8.6 t/s generation |
| Backend wiring | discover binaries + models | 6 models discovered, LD_LIBRARY_PATH set |

### Verified end-to-end user journeys
1. Registration → contact verification → payment eligibility → protected workspace access (all enforced backend-side).
2. Unauthenticated request → 401; ineligible account → 403 (payment gate cannot be bypassed).
3. Real tool execution: `fs.write`/`fs.read` land inside the authorized workspace.
4. Agent objective ("list the files…") → routed to real `fs.list` tool → completed.
5. Conversation persistence (create, add messages, reload).
6. Path traversal (`../../../etc/passwd`) → 403; `fs.write` outside workspace → refused, file not created.

