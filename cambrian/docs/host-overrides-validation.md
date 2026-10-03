# Prototype validation and change summary

Baseline: Firefox 157.0, upstream `FIREFOX_157_0_RELEASE`
(`fdd757a2e09c9471cddf383e64e631e4ce178499`). Work is on
`feature/host-overrides`; the archive's `manifest.json` records its exact source
revision, compiler versions and actual verification mozconfig.

## Completed checks

Executed on Ubuntu Linux x86_64, using a native optimized build with tests
compiled, fresh browser profiles and `acceptInsecureCerts=false`:

| Required check (Agent) | Result | Evidence |
| --- | --- | --- |
| Native build | Passed | `logs/build-final.log`, final successful run |
| DNS xpcshell regression | Passed, 29 subtests | `logs/xpcshell-host-overrides.log` |
| Immutable TLS snapshot/session-key GTests | Passed, 2 tests | `logs/gtest-hostoverride.log` |
| Existing TLS session-resumption regression | Passed, 154 subtests | `logs/xpcshell-session-resumption.log` |
| Existing private-browsing session-cache regression | Passed, 17 subtests | `logs/xpcshell-pbm.log` |
| Browser matrix, socket process on | Passed, 33 checks | `logs/browser-socket.json` and sibling resolver logs |
| Browser matrix, socket process off | Passed, 33 checks | `logs/browser-parent.json` and sibling resolver logs |
| ESLint / preference lint / whitespace checks | Passed | `logs/final-eslint.log`, source worker lint checks |

Logs are under `/home/codex/builds/cambrian-firefox-host-overrides/`; reproducible
commands and fixture prerequisites are in `cambrian/tests/README.md`.
The browser matrices confirm actual socket-process PID/on and absent/off, mapped
TCP destination `127.0.0.2`, original Host/authority and SNI, HTTP/1.1 and H2,
WS/WSS Origin, redirects, cookies, same-origin/CORS, ordinary-host controls,
synthetic DNS A/suppressed HTTPS records with no actual resolver dispatch,
Alt-Svc trap avoidance, live-proxy rejection, and mapping change/removal.

A deliberately invalid certificate loads only under the matching insecure
mapping. Normal-mode, ordinary-host, and HSTS cases produce fresh bad-certificate
handshake failures. In unchanged insecure mode, three sequential connections
report `sessionReused = false, true, true`; switching to normal mode rejects
the bad certificate again. The toolbar DOM checks prove the normal label,
explicit insecure warning, and hidden indicator for an ordinary host.

The snapshot tests prove a socket created before activation cannot acquire an
insecure snapshot from a later preference edit. Authorization tests reject
empty, strict, removed, changed-address and mismatched-peer contexts. Session
keys isolate mode/address changes. A complete timed late-handshake race has not
been reproduced; the review and immutable-context/key tests establish the
intended protection without claiming instantaneous cross-process revocation.

Optional Human/owner check: extract the archive, start its portable launcher,
set the documented preference and inspect the label/layout in a GUI session.
No human interaction is required for integration after the required automated
checks above. The chrome DOM and visible label bounds are checked; interactive GUI
appearance has not been inspected in a human session.

## Files and purpose

- `netwerk/base/HostOverride.{h,cpp}` and `StaticPrefList.yaml`: shared strict
  parser and default-empty profile preference.
- `nsHostResolver.{h,cpp}`: uncached synthetic address records before ordinary
  DNS/TRR/cache dispatch, using the existing external-resolution transport path.
- HTTP channel, connection-info/manager/entry/handler and `AlternateServices`:
  prevent alternate routing/proxies/coalescing, isolate connection identity and
  invalidate network/TLS state on edits.
- NSS socket control, certificate verification and socket-process IPC: immutable
  context and session-key partitioning, exact-peer scoped acceptance after
  normal verification and existing policy guards; no stored cert exceptions.
- DNS service interface/implementations and browser URL bar files: authoritative
  configuration getter and selected-tab normal/insecure indicator.
- Networking xpcshell, TLS GTests and `cambrian/tests/`: repeatable regression and
  real-browser protocol/security evidence.
- `cambrian/docs/`, README, verification mozconfig and packaging helper:
  investigation, configuration, limitations, reproducible checks and bundled
  documentation/fixture.

IPv4, exact ASCII hostnames, all ports and direct desktop Linux connections are
the initial scope. HTTP/3, Alt-Svc, HTTPS/SVCB routing, proxies and WebTransport
cannot bypass a mapping. Pinned-certificate mode and a management page remain
future work. Response-cache contents are retained; use a cache-bypassing reload.
