# Host override browser tests

Prerequisites: Linux Firefox built from this branch, Python 3, Node.js with
HTTP/2 support, and OpenSSL. No pip/npm dependencies, root access, or external
DNS/server are required. Servers bind only to 127.0.0.1 and 127.0.0.2 on random
nonprivileged ports. The harness creates and removes a fresh profile and local
CA; it never changes an existing Firefox profile. Marionette runs with
`acceptInsecureCerts=false`.

Run from a full source checkout, or use the bundled `tests/` directory:

```sh
python3 cambrian/tests/host_overrides_browser.py \
  --firefox /path/to/native/app/firefox \
  --socket-process on --report /tmp/host-overrides-socket.json
python3 cambrian/tests/host_overrides_browser.py \
  --firefox /path/to/native/app/firefox \
  --socket-process off --report /tmp/host-overrides-parent.json
```

Use the native executable, since the portable launcher intentionally rejects
profile arguments. The default mapping is `dev-test.invalid=127.0.0.2`; the
harness edits it during the test. Exit 0 and `passed:true` mean every assertion
passed. Preserve the JSON and adjacent `.mozlog` files as evidence. Baseline
mode (`--baseline`) is an optional negative control with an unmodified browser.

The browser matrix checks destination address, Host/HTTP2 authority, original
SNI, ALPN, HTTP/HTTPS/H2, WS/WSS, redirects, cookies and browser same-origin/CORS
behavior. Ordinary localhost requests are positive controls. DNS A queries
must return only the synthetic IP, HTTPS records must fail, and resolver logs
must contain synthetic/suppression evidence with no real lookup for the unique
`dns-proof.invalid` mapping. HTTP/3 stays enabled globally; an HTTPS Alt-Svc
advertisement must never connect to the alternate TLS/H2 trap.

Invalid TLS is rejected in normal mode and for ordinary hosts, accepted only
under the explicit matching insecure mapping, then rejected after mode removal.
HSTS remains a rejection gate. Three sequential connections under unchanged
insecure configuration must demonstrate actual TLS session resumption, followed
by rejection after switching to normal mode. Each negative TLS check requires a
new server-side handshake error. Mapping changes/removal, a live proxy control,
and the normal/insecure/ordinary toolbar indicators are also checked.

## Manual fixture

To keep a server running for interactive use, import this module and generate
local certificates, then start Node:

```sh
mkdir -p /tmp/override-fixture
python3 -c "from cambrian.tests.host_overrides_browser import make_certs; make_certs('/tmp/override-fixture')"
node cambrian/tests/local_server.js /tmp/override-fixture /tmp/override-server.json
```

Node prints listener ports. In an isolated Firefox profile, set
`network.host_overrides` to `dev-test.invalid=127.0.0.2`. Import
`/tmp/override-fixture/ca.crt` as a trusted website CA for that test profile.
Browse `https://dev-test.invalid:HTTPS_PORT/json`; the response reports the
server's local IP, original Host and SNI. The URL and toolbar label retain the
hostname. With `dev-test.invalid=127.0.0.2|insecure`, the `badHttps` port should
also load without adding a certificate exception. Remove `|insecure` and reload;
it must show Firefox's certificate error. `/tmp/override-server.json` records
connections. Stop Node when finished; remove the temporary fixture yourself.

## Native regression tests

The default packaging mozconfig disables tests. Build with the provided
verification config instead to compile xpcshell and GTest support:

```sh
export MOZCONFIG="$PWD/cambrian/mozconfig.host-overrides-tests"
export MOZ_OBJDIR="$HOME/builds/host-overrides-tests/objdir"
export PATH="$HOME/.mozbuild/cargo/bin:$PATH"
export RUSTUP_HOME="$HOME/.mozbuild/rustup-home"
export CARGO_HOME="$HOME/.mozbuild/cargo"
./cambrian/build.sh -j4
./mach xpcshell-test netwerk/test/unit/test_host_overrides_pref.js
./mach gtest 'HostOverride.*'
./mach xpcshell-test security/manager/ssl/tests/unit/test_session_resumption.js
./mach xpcshell-test security/manager/ssl/tests/unit/test_ssl_session_cache_pbm_exit.js
```

Required checks are performed by the agent/CI: the DNS test covers matching,
updates/removal, malformed config, address-family rejection, and suppression of
non-address records. GTests cover immutable socket snapshots, session namespaces,
private origin attributes, and peer/snapshot/current authorization mismatches.
Existing TLS regressions and both real-browser matrices are required because
this change affects certificate exceptions and resumed sessions. Record command
exit status, test summaries, source revision and JSON/log evidence. An optional
human/owner GUI check can confirm label layout and interactive navigation; it is
not an integration gate once the automated browser checks pass.
