# Bound browser connection shutdown

Type: task
Status: resolved
Triage: ready-for-agent

## Goal

User requested automatic closure of browser connections after a brief timeout,
without requiring Dashboard tabs to close for deployment. Give HTTP/SSE requests
five seconds to finish, then cancel them and run normal application cleanup.
Keep the deployment process-exit/port-release checks and BLE cleanup. Do not
kill the entire process as the normal browser-disconnection mechanism.

## Validation

Start the actual service with an SSE request held open, signal shutdown, and
verify bounded exit plus completed lifespan cleanup. Use no Bluetooth hardware.
Run the full offline suite and changed-module typechecking.


## Answer

Set Uvicorn's HTTP graceful-shutdown timeout to five seconds at the service
entry point. Remaining HTTP/SSE tasks are cancelled, then application lifespan
shutdown runs. The deployment script retains its separate 60-second process
shutdown deadline, PID checks, and port-release check. No normal process kill
was introduced. Docs now permit open tabs during restart and distinguish
HTTP request cancellation from Poller/BLE cleanup.

Regression uses the actual serve entry point, real HTTP/SSE, and SIGINT.
Before the fix it failed because an open SSE blocked exit beyond eight seconds.
After the fix it passes and confirms lifespan cleanup finishes. Polling is
disabled in this test, so it does not claim hardware/BLE cleanup validation.
Full offline suite: 192 passed, 2 live tests deselected. App typechecking and
diff checks pass. Standards and Spec reviews found no violations/mismatches;
Standards noted the test's deliberate hardware-cleanup coverage limit.

Committed locally for the next restart; no deployment or live restart performed.
The current service still runs e692089 without the new HTTP timeout. Existing
open connections can block the first upgrade; subsequent restarts use the new
policy. No request to close user tabs was made during this change.
