<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Render pack

Steps this pack adds to core commands. Each command reads its own section at its hook line.

## Pack facts

| Fact | Value | Meaning |
|---|---|---|
| `DEPLOY_SERVICES` | see below | Which Render service runs which code |
| `ENV_GROUPS` | `{{ENV_GROUPS}}` | Each env group and the services that must link it |
| `RUNTIME_MEMORY_LIMIT` | `{{RUNTIME_MEMORY_LIMIT}}` | The memory ceiling of the smallest instance that runs app code |

`DEPLOY_SERVICES` (code area → service; one row per area, shared code lists every service built from it):

{{DEPLOY_SERVICES}}

**Access.** The read-only tools of the Render MCP server `render`: `list_services`, `get_service`, `list_deploys`,
`get_deploy`, `list_events`, `list_logs`, `list_log_label_values`, `get_metrics`. If the account has several
workspaces, `list_workspaces` and use the one that holds the services above. Never call `trigger_deploy`,
`update_environment_variables` or a `create_*` tool: the first is a release (G1), the second replaces a service's
whole variable list. **Codex:** without the Render MCP, record each Render check as NEEDS_CONTEXT, never as passed.

**Deploy statuses.** In progress: `created`, `build_in_progress`, `pre_deploy_in_progress`, `update_in_progress`.
Done: `live`. Superseded: `deactivated`. Failed: `build_failed`, `pre_deploy_failed`, `update_failed`. `canceled`
means it never went live.

## /operate

Before adding a subprocess, a large download, an in-process batch or any memory-heavy pass, answer these and put the
answers in the hand-off:

1. **Which service runs it,** from `DEPLOY_SERVICES`? Heavy work on a web service can take the API down with it
   when it runs out of memory.
2. **Does it fit?** The box has `<RUNTIME_MEMORY_LIMIT>`, and the runtime is already resident, so real headroom is
   less. A local run proves the change works, never that it fits. If the cost is memory, measure peak memory and say
   so; don't report it verified on a laptop run alone.
3. **Is it bounded?** Heavy local work runs behind a concurrency gate (one at a time unless measured), with a
   timeout and a byte cap.
4. **Is large media streamed?** Download to disk and process from the file. Enforce the byte cap **during** the
   download, not after it. Never hold a large file in memory, let alone twice. Remove the temp file in a `finally`.
5. **What happens when it fails?** A failed step after a paid provider call must not throw away the provider's
   result: keep it, retry the local step, and clean up only your own partial output.

## operate lenses

**Runtime fit.** Does any new work run on a service with no measured headroom for it? Is every download streamed
with a byte cap enforced during the transfer? Can a failed local step lose work a provider was already paid for?

## /verify

**Step 0 (pre-merge).** A feature branch is deployed nowhere; Render builds from `<MAIN_BRANCH>`. The local run is
the pre-merge evidence. For a memory-heavy change, the verdict says plainly that the local run shows it works, not
that it fits `<RUNTIME_MEMORY_LIMIT>`; peak memory after deploy is part of the post-merge half.

**Step 3 (post-merge).**

1. **Affected services.** Map each changed path to its services with `DEPLOY_SERVICES`. Shared code → **every**
   service built from it. A service with auto-deploy off (`get_service`) doesn't deploy on merge: deploying it is
   a release (G1). Say so, and leave it to the owner.
2. **Deploy.** For each affected service, `list_deploys` and find the deploy of the merge commit (or a newer one).
   - In progress → check again every 30 seconds, up to 20 minutes. Still not live → `⚠️ PARTIAL`, naming the
     service and status.
   - `live` → record its id and time.
   - `build_failed`, `pre_deploy_failed` or `update_failed` → **the merge broke `<MAIN_BRANCH>`.** Say so at once
     and loudly, notify, don't start other work. Read the failed deploy's logs for the cause.
   - `deactivated` → a newer deploy replaced it; check that one instead.
3. **Logs.** `list_logs` for each service, from the deploy's time, filtered by the change's log prefix or text. Find
   the change's log line; none → `⚠️ PARTIAL`.
4. **Memory-heavy change.** `get_metrics` (memory) for the service over the first real runs: peak under
   `<RUNTIME_MEMORY_LIMIT>`, and no restart in `list_events`.

`Post-merge:` line: `<service> — deploy <id> live at <time>; log line seen` (one per service).

## /ship

- **At the hook after Step 2:** record each affected service's current `live` deploy id (`list_deploys`) in
  `.claude/state/<ticket>/render-before.txt`. It is the rollback target, and it tells the new deploy apart.
- **Step 4.1:** run this pack's `/verify` Step 3. A failed build or update follows `/ship`'s "main is broken" path.

## /investigate

- **Deployed bug:** `list_logs` on the service from `DEPLOY_SERVICES`, narrowed by time window, level and the
  suspected file's log prefix. `list_log_label_values` shows which labels exist to filter on.
- **Restarts or out-of-memory:** `list_events` for restarts and deploys around the failure; `get_metrics` for
  memory and CPU. Memory climbing to `<RUNTIME_MEMORY_LIMIT>` before a restart is the out-of-memory signature: heap
  growing with RSS points at a retained reference; RSS growing with a flat heap points at native memory to bound.
- **Config drift** (works locally, fails on Render): is the env var present on that service? Check by name only
  (see `/release`).
- **Which code is running:** the live deploy's commit (`get_deploy`) against the commit you are reading.

## /release

1. **Services.** For each service in `DEPLOY_SERVICES`: `get_service` shows it builds from `<MAIN_BRANCH>`, is not
   suspended, and its latest deploy is `live` with a commit inside the release range. Record each live deploy id;
   these are the rollback targets.
2. **Env groups.** Each service links the groups `ENV_GROUPS` says it needs. The Render API can't link an env group,
   so a missing link is an owner task in the dashboard: say which service and which group.
3. **New env vars** (core Step 3): each one is present on every service that reads it, checked by **name** only.
   Never print, copy or log a value. If the tools can't show names without values, ask the owner to confirm each
   name in the dashboard and record `UNCONFIRMED` until they do.
4. **Rollback.** The code rollback target per service is the deploy id from item 1. A dashboard rollback is a
   production change: G1, done by the owner.

`Pack sections:` line: `render: <n> services live from <MAIN_BRANCH> · env groups linked ✅ | <service> missing <group> · new vars ✅ | UNCONFIRMED <names>`.
