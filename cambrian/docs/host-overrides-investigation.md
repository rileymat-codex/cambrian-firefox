# Host override prototype: investigation and implementation hook

Baseline: Firefox 157.0 (`FIREFOX_157_0_RELEASE`), fork revision
`6b8dbe7a43fe6be071827f3ceac38d7e385dd661`. This note precedes the networking patch.

## Address resolution and hostname identity

`nsHttpChannel::BeginConnect` builds `nsHttpConnectionInfo` from the URL
origin; `SetupTransaction` supplies it to the HTTP transaction. Connection
establishment uses `DnsAndConnectSocket::TransportSetup`
and the Happy Eyeballs connection establishers to call
`nsIDNSService::AsyncResolveNative`. `nsDNSService::AsyncResolveInternal`
delegates to `nsHostResolver::ResolveHost`; completed address records become
`nsDNSRecord` objects. Across process boundaries, `DNSRequestParent` serializes
the addresses and `ChildDNSRecord` reconstructs the record.

HTTP already supplies that record to `nsSocketTransportService::CreateTransport`
or `CreateRoutedTransport`. In `netwerk/base/nsSocketTransport2.cpp`,
`nsSocketTransport::Init` sets `mExternalDNSResolution` when given a record.
`ResolveHost` then posts DNS completion without performing another lookup.
Thus a synthetic address record fits existing external-resolution plumbing;
neither a new socket API nor URL rewriting is needed.

`nsHttpConnectionInfo` keeps the authenticated origin separately from optional
Alt-Svc/SVCB routing destinations. Replacing addresses leaves the origin and
HTTP Host/HTTP2 authority unchanged. `nsNSSIOLayer.cpp` passes the socket's
hostname to `SSL_SetURL`; certificate verification uses the same hostname.
TLS SNI therefore remains the URL hostname. Cookies and web origins continue
to follow the original URL.

## Smallest hook

Add a default-empty, profile-local `network.host_overrides` string preference
and a small shared parser. Initial syntax is comma-separated exact ASCII hosts:
`dev-test.invalid=127.0.0.2` and optionally
`dev-test.invalid=127.0.0.2|insecure`. IPv4 and direct connections are the initial
scope. No wildcard matching or implicit insecure mode.

In `nsHostResolver::ResolveHost`, check the configured host before cache lookup
or native/TRR dispatch. Construct a fresh, uncached `AddrHostRecord`/`AddrInfo`
using the existing record factory, analogous to the loopback fast path. Deliver
it through the normal callback after releasing resolver locks. An uncached
record cannot be overwritten by an older in-flight DNS lookup. Return no
result for other DNS record types for that host, including HTTPS RR/SVCB, so
they cannot issue DNS requests or change the destination. IPv6-only requests
fail without DNS fallback. Nonmatching hosts use the existing resolver path.

## Protocol and connection state

HTTP/2 coalescing uses resolved IPs but can share a socket across hostnames.
Exclude overridden origins and candidate connections from cross-origin
coalescing; retain same-origin HTTP/2 multiplexing. Connection keys must
distinguish mapping changes, because existing keys contain hostname/port but
not the selected destination IP.

HTTP/3 uses `HttpConnectionUDP` and DNS address records too, but Alt-Svc or
HTTPS RR may first select a different routed host. For this prototype, skip
Alt-Svc and disable HTTP/3 for overridden origins, including speculative
connections. Never accept an alternate route around the configured address.
Proxy connections are unsupported and must fail explicitly for overridden
origins rather than silently using proxy-side DNS.

On configuration changes, close existing HTTP connections, flush DNS and
Alt-Svc state, and clear NSS sessions and external resumption tokens. Firefox
already has `net:cancel-all-connections` and
`SSLTokensCache::ClearSessionCacheAndTokens` machinery, including socket-process
cache invalidation. A blunt flush is appropriate for this development feature.
Outstanding operations may be aborted; subsequent connections must use the
new configuration.

## Optional insecure TLS

`SSLServerCertVerification.cpp::AuthCertificateParseResults` performs ordinary
verification first, classifies overridable errors, checks HSTS/static pinning,
then consults `nsICertOverrideService::HasMatchingOverride`. Existing exceptions
are exact host, port, origin attributes, and certificate fingerprint. Global
test-only security-disable paths are unsuitable.

Prefer a connection-scoped acceptance gate in that existing failure path.
It must require an active exact-host insecure mapping and evidence that this
connection's peer address matches the configured address. Preserve the existing
error category, which prevents an invalid-certificate connection from being
coalesced to another host. Keep HSTS, static pinning, and non-overridable failures
intact. This produces no persistent certificate exceptions and removing the
mapping removes the bypass. The peer-address data flow needs to cover
`PSocketProcessBackground::InitVerifySSLServerCert`, since socket-process handshakes may be verified in the
parent process; this is reviewed before the second patch.

The implementation captures the TCP peer with `PR_GetPeerName` in
`AuthCertificateHook`, canonicalizes it, and carries it with an immutable
`NSSSocketControl` override snapshot through the local verification job and
`PSocketProcessBackground::InitVerifySSLServerCert` into the parent verifier.
The parent requires both the snapshot and its current exact-host mapping to be
insecure, with snapshot address = current address = actual peer address. ECH
public-name verification and QUIC carry no override authorization. No temporary
or persistent `nsICertOverrideService` entry is created.

Closing sockets and flushing tokens asynchronously leaves an ordering window:
a pending handshake can otherwise insert an insecure session after the flush.
Each NSS socket captures its mapping at construction. Its peer ID has a prefix
encoding mapping presence, IPv4 address, and TLS mode, preserving the existing
host/port/origin-attributes suffix. Internal NSS sessions and external tokens
therefore use separate namespaces for ordinary, strict, insecure, and different
addresses, even if a late token arrives. Preference changes cannot turn an
already-created strict socket into an insecure-authorized one. This does not
promise instantaneous cancellation of every previously created socket across
processes; aborted in-flight work can require a reload.

Future pinned-certificate mode would need to check the configured SHA-256
fingerprint even when ordinary certificate verification succeeds, rather than
only accepting an overridable error. `nsIX509Cert` already exposes the
SHA-256 fingerprint used by `nsCertOverrideService`; a future host-override
entry could store and compare that value in the same connection-scoped gate.
That mode would also require the fingerprint/mode to be part of the immutable
session-cache key and would need the existing session/token invalidation when
the entry changes. No pinning mode is implemented here.


## Verification plan

Use local servers bound to `127.0.0.2`, nonprivileged ports, generated CA and
self-signed certificates, and a fresh browser profile with normal TLS checking
enabled. Record local destination, Host/authority, TLS SNI, request Origin,
cookies, negotiated protocol, and connection identity. Exercise HTTP/1.1,
HTTPS/1.1, HTTP/2, WS/WSS, redirects, same-origin/CORS behavior, mapping changes,
and rejected ordinary/normal-mode invalid certificates. Resolver logs must show
synthetic completion and no native/TRR lookup for active hosts. Include an
Alt-Svc trap destination and run with socket-process networking enabled.
