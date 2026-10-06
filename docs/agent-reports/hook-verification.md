# Pipeline hook verification

STATUS: DONE

Date: 2026-09-29
Scope: `.claude/hooks/check-write.ps1`, `.claude/hooks/notify.ps1`, `.claude/settings.json`, `.claude/pipeline.json`

## Summary

All six checks pass. No hook logic was changed — one finding turned out to
already be correct, and the rest verified clean on first run.

## 1. pwsh vs powershell.exe

This machine has **no `pwsh` (PowerShell 7)** installed — only Windows
PowerShell 5.1 (`powershell.exe`). Confirmed with `which pwsh` (not found) and
`pwsh -NoProfile -Command ...` (command not found in Git Bash).

`.claude/settings.json` already invokes hooks via
`"command": "powershell.exe"` (not `pwsh`) for `PostToolUse`, `Stop`,
`Notification`, and `SubagentStop`. **No change needed** — settings.json
already matches the environment. (The task's suggested invocation line uses
`pwsh`, which doesn't exist here; all verification below was run with
`powershell.exe` instead, matching what settings.json actually calls.)

## 2. backend/tmp_check.py = "# TODO remove me" -> expect exit 2

Command:
```
'{"tool_input":{"file_path":"backend/tmp_check.py"}}' | powershell.exe -NoProfile -File .claude\hooks\check-write.ps1
```
Result: **exit 2**
```
check-write: backend/tmp_check.py failed 1 check(s). Fix the file now:
  BANNED backend/tmp_check.py line 1: 'TODO' -> # TODO remove me
```
PASS.

## 3. backend/tmp_check.py = "x = 1" -> expect exit 0

Same file, content replaced. Result: **exit 0**, no output. PASS.

## 4. contracts/tmp_check.py = "# TODO remove me" -> expect exit 0 (testGlobs exempt)

`contracts/**` is listed in both `sourceGlobs` and `testGlobs` in
`pipeline.json`, so it's syntax-checked (no-op, `syntaxCheck` is `null` in
this greenfield repo) but exempt from the banned-pattern scan per
`Test-SourceFile` in `lib.ps1`. Result: **exit 0**. PASS.

## 5. frontend/src/tmp_check.ts = "const guilt = 1" -> expect exit 2 (7.9 lexicon)

Result: **exit 2**
```
check-write: frontend/src/tmp_check.ts failed 1 check(s). Fix the file now:
  BANNED frontend/src/tmp_check.ts line 1: 'guilt' -> const guilt = 1
```
`guilt` is part of the ARCHITECTURE.md §7.9 lexicon list in `pipeline.json`'s
`banned` array. PASS.

## 6. notify.ps1 toast

Command:
```
'{"hook_event_name":"Notification","notification_type":"idle_prompt","message":"Hook verification test toast - please confirm you saw this"}' | powershell.exe -NoProfile -File .claude\hooks\notify.ps1
```
Result: exit 0, `[notify] delivered via WinRT`. **User confirmed the toast
was visible on screen.** PASS.

## 7. Cleanup

All temp files (`backend/tmp_check.py`, `contracts/tmp_check.py`,
`frontend/src/tmp_check.ts`) and the now-empty directories created solely to
hold them (`backend/`, `contracts/`, `frontend/`) were deleted. Repo tree is
back to its pre-verification state (only `ARCHITECTURE.md` and `.claude/`).

## Changes made

None. Every check passed against the existing hook implementation and
existing settings.json; no weakening or strengthening of any check was
required.
