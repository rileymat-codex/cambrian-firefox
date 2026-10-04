# CambrianFirefox: intent and implementation map

This fork started with two goals: produce a native Ubuntu Firefox build that
can run alongside the owner's existing Firefox, and add a development feature
equivalent to `curl --resolve` inside the browser. The starting source is
Firefox 157.0, tag `FIREFOX_157_0_RELEASE`, upstream commit
`fdd757a2e09c9471cddf383e64e631e4ce178499`.

The first working host-override build is tagged
`cambrian-157.0-host-overrides-1`, at commit
`a18103a7e7d32b84f97d3afc36fe618e3e5245e6`. The implementation lives on
`feature/host-overrides`; at that milestone, `master` contains the portable
packaging baseline only. This document describes that implementation, including
its deliberate prototype limitations.

## What the user gets

The portable archive contains a launcher, the native browser, build provenance,
documentation, and a local test fixture. The launcher always uses `--no-remote`
and a separate profile under
`${XDG_STATE_HOME:-$HOME/.local/state}/cambrian-firefox/profile`. It does not
install into system directories or register itself as the default browser.
Profile-selection arguments are rejected to protect existing profiles; updates
and default-browser checks are disabled for the packaged fork.

In that browser's `about:config`, create or edit one **String** preference named
`network.host_overrides`. For example, enter this value without surrounding
quotes:

```text
dev-test.invalid=127.0.0.2,other-test.invalid=127.0.0.3|insecure
```

The first mapping uses normal certificate verification. The second explicitly
permits eligible certificate errors for its configured endpoint. Both preserve
the original hostname in the URL, HTTP Host/HTTP2 authority, TLS SNI, cookies,
and web origin. Only the destination address changes, and an active mapping
avoids ordinary DNS resolution for that hostname. The URL bar shows the mapping
and a conspicuous red warning when insecure mode is configured.

The intent is to test a particular server using the site's real identity,
without editing system DNS or hosts files. It is a profile-local development
tool, not a general routing system. See [configuration and limitations](host-overrides.md)
for syntax, invalid-entry handling, and reload behavior.

## Where to look in the implementation

### Address substitution through existing DNS plumbing

`netwerk/base/HostOverride.{h,cpp}` contains the shared parser and
`LookupHostOverride`. `modules/libpref/init/StaticPrefList.yaml` declares the
default-empty preference. Keep parsing centralized: networking, TLS, and the
browser indicator must agree about whether an entry is active.

`netwerk/dns/nsHostResolver.cpp`, in `nsHostResolver::ResolveHost`, supplies a
fresh, uncached synthetic address record before cache lookup or native/TRR DNS
dispatch. Other record types for the mapped host are suppressed. The record
uses the existing DNS callback and IPC machinery, so both parent-process and
socket-process networking receive the same address.

HTTP already passes resolved records into socket transport. In
`netwerk/base/nsSocketTransport2.cpp`, the existing `mExternalDNSResolution`
path accepts that record without resolving the hostname again. That file did
not need modification. Retaining the original hostname in connection identity
also preserves Host and SNI naturally; there is no URL rewrite or manual Host
header replacement. The [investigation note](host-overrides-investigation.md)
traces the complete call path and explains the choice of hook.

### Routing and stale connection state

The related changes under `netwerk/protocol/http/` make address substitution
effective even when Firefox could otherwise reuse or reroute a connection:

- `nsHttpChannel` and `AlternateServices` suppress alternate routing and reject
  unsupported mapped-host paths, including actual proxy connections.
- `nsHttpConnectionInfo` includes the override address and TLS mode in connection
  identity so different configurations cannot share the same pool key.
- `nsHttpConnectionMgr` and `ConnectionEntry` prevent cross-origin coalescing
  while any valid override is active. Same-origin HTTP/2 pooling remains usable.
- `nsHttpHandler` observes preference edits, aborts pooled connections, and
  flushes DNS, Alt-Svc, and TLS session/token state.

HTTP/3 is disabled for mapped hosts in this prototype; HTTPS RR/SVCB and
Alt-Svc must not select another destination. These guards are part of
correctness, not optional performance tuning. Cache flushing is deliberately
broad. HTTP response-cache contents remain intact, and connection closure is
asynchronous, so use a cache-bypassing reload to test a changed mapping.

### Insecure TLS remains tied to a specific connection

`security/manager/ssl/SSLServerCertVerification.cpp` runs ordinary certificate
verification first. Its failure path retains the existing error categorization
and HSTS/static-pinning guards, then checks `MatchesInsecureHostOverride`.
Acceptance requires all three to agree:

1. The immutable override captured when the socket was created is insecure.
2. The current exact-host override is still insecure with the same address.
3. The actual TCP peer address matches that address.

`NSSSocketControl.{h,cpp}` owns the immutable snapshot and adds the address and
TLS mode to the TLS peer/session identity. This separates ordinary, normal-mode,
insecure-mode, and changed-address sessions, including tokens arriving after a
cache flush. Do not replace this with a preference lookup only at handshake
completion: an older socket must not gain insecure authorization from a later
preference edit.

The peer address and snapshot travel through `VerifySSLServerCertChild/Parent`
and `netwerk/ipc/PSocketProcessBackground.ipdl` to parent-side verification.
Both process configurations therefore enforce the same gate. The implementation
uses the existing certificate-error handling location, but creates no
`nsICertOverrideService` entries and has no global TLS-disable switch.

### Browser feedback

`browser/base/content/browser-hostOverrideIndicator.js` reads the authoritative
mapping through `nsIDNSService.getHostOverride`, implemented in both
`nsDNSService` and `ChildDNSService`. URL-bar markup, shared CSS, and browser
script registration provide a selected-tab indicator that responds to navigation
and preference edits. It describes the current configuration; it does not prove
where a previously cached response originated. A management page is not yet
implemented.

## Commits that introduced the changes

The following commits are in application order. Links point to the fork's
commit diffs; the short IDs also work with `git show` in a local checkout.

| Commit | Intent and principal changes |
| --- | --- |
| [6b8dbe7a43fe](https://github.com/rileymat-codex/cambrian-firefox/commit/6b8dbe7a43fe6be071827f3ceac38d7e385dd661) | Portable Ubuntu baseline: `cambrian/` bootstrap/build/package scripts, isolated launcher, build configuration, provenance manifest, and launcher tests. |
| [542802c3090c](https://github.com/rileymat-codex/cambrian-firefox/commit/542802c3090c811311af1c28e84d2ab682e5fb08) | Core mapping: preference/parser, synthetic DNS, routing restrictions, connection keys and invalidation, DNS tests, and source investigation note. |
| [92a300321dfd](https://github.com/rileymat-codex/cambrian-firefox/commit/92a300321dfd5e84da8643b9ee88caa8ca986a66) | Scoped insecure TLS: immutable socket context, actual-peer checks, verification IPC, separate session identities, and security GTests. |
| [68e3e3ba98e8](https://github.com/rileymat-codex/cambrian-firefox/commit/68e3e3ba98e83c07be0ad4b60157088e39d69c2e) | Visible browser feedback: DNS-service getter, URL-bar mapping and TLS warning, and configuration documentation. |
| [8a15187f4291](https://github.com/rileymat-codex/cambrian-firefox/commit/8a15187f4291609b6670cd1e021ee9672669addd) | Reproducible acceptance fixture: local HTTP/HTTPS/H2/WS servers and real-browser checks for destination, identity, TLS, and configuration changes. |
| [a18103a7e7d3](https://github.com/rileymat-codex/cambrian-firefox/commit/a18103a7e7d32b84f97d3afc36fe618e3e5245e6) | Working milestone: bundled docs and fixture, test-enabled mozconfig, validation record, and visible-indicator assertions. |

To review the host-override feature as one diff, excluding the earlier packaging
baseline:

```sh
git diff 6b8dbe7a43fe..a18103a7e7d3
```

## Evidence and boundaries

The [validation record](host-overrides-validation.md) lists completed native,
xpcshell, GTest, and browser checks. The browser fixture exercises HTTP/1.1,
HTTPS/1.1, HTTP/2, WS/WSS, redirects, cookies, same-origin behavior, DNS
suppression, proxy rejection, Alt-Svc avoidance, mapping edits, and TLS
resumption. It ran with socket-process networking both enabled and disabled,
using fresh profiles and `acceptInsecureCerts=false`. Reproduction commands and
fixture dependencies are in the [test guide](../tests/README.md).

The first version supports IPv4 targets, exact ASCII hostnames, all ports for
each mapping, and direct desktop Linux connections. It does not implement
wildcards, per-port mappings, IPv6 targets, mapped-host HTTP/3, proxies,
WebTransport, pinned-certificate mode, or a management UI. HSTS and existing
pinning restrictions remain enforced even in insecure mode. Structural tests
cover immutable session context; a complete timed late-handshake race has not
been reproduced, and instantaneous cross-process revocation is not promised.

The native package's `manifest.json` records its precise source revision and
build configuration. Later documentation commits do not change the already
published milestone archive.
