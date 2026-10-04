# CambrianFirefox 157.0

This fork packages the `FIREFOX_157_0_RELEASE` source revision
`fdd757a2e09c9471cddf383e64e631e4ce178499` from
`https://github.com/rileymat-codex/cambrian-firefox`. It is a working fork
label, not an official Mozilla binary. The browser inside the archive keeps
Firefox's upstream application name and resources, including its Mozilla
license files.

The archive is self-contained and does not register a desktop entry, change
the system default browser, or install into system directories. On extraction,
run `./cambrian-firefox/firefox [options] [URLs]`. The launcher resolves its
own directory, so paths containing spaces are supported. It always passes
`--no-remote` and uses the isolated profile
`${XDG_STATE_HOME:-$HOME/.local/state}/cambrian-firefox/profile`, created with
mode 700. Profile-selection options are rejected to prevent accidental use of
an existing Firefox profile. `--headless` and URLs are passed through.

Ubuntu runtime libraries are expected to be available on the host (including
GTK and related desktop libraries). Other Linux distributions may need their
equivalent packages.

## Host override prototype

For the reasons behind this fork, a map of the implementation, and the commits
that introduced each part, start with [fork changes](docs/fork-changes.md).

In `about:config`, set the string preference `network.host_overrides`:

```text
dev-test.invalid=127.0.0.2
```

For an explicitly trusted development endpoint with an invalid certificate:

```text
dev-test.invalid=127.0.0.2|insecure
```

The URL, Host header, TLS SNI, cookies, and origin retain the hostname. Entries
are comma-separated, IPv4-only, exact hosts, and apply to every port. A blank
preference removes overrides. Edits abort pooled connections and clear network
and TLS caches. HSTS and pinning restrictions remain enforced. Proxy,
WebTransport, HTTP/3 and alternate routing are unsupported for mapped hosts.
Read [configuration and limitations](docs/host-overrides.md), the
[source investigation](docs/host-overrides-investigation.md), and
[validation/change summary](docs/host-overrides-validation.md). The bundled
`tests/` directory contains reproducible loopback browser tests.

## Build from source

Use a full Firefox checkout at this repository revision. The workspace's
sparse packaging worktree contains only `cambrian/`; it is not a build source
checkout. A reproducible command sequence is:

```sh
git clone --branch feature/host-overrides https://github.com/rileymat-codex/cambrian-firefox.git
cd cambrian-firefox
git rev-parse HEAD
export MOZ_OBJDIR="$HOME/builds/cambrian-firefox-157.0/objdir"
export CAMBRIAN_PACKAGE_OUTPUT="$HOME/CambrianFirefox-157.0-ubuntu.tar.xz"
./cambrian/bootstrap.sh
./cambrian/build.sh -j4
./cambrian/package.sh
mkdir -p "$HOME/apps/cambrian-firefox"
tar -xJf "$CAMBRIAN_PACKAGE_OUTPUT" -C "$HOME/apps/cambrian-firefox"
"$HOME/apps/cambrian-firefox/cambrian-firefox/firefox" --headless about:blank
```

Bootstrap uses Mozilla's dependency setup without system changes. Set
`MOZ_OBJDIR` to an external object directory and
`CAMBRIAN_PACKAGE_OUTPUT` to the desired outer archive path.
The scripts keep Rust and Cargo under the user-owned `${MOZBUILD_ROOT:-$HOME/.mozbuild}`
tree (`cargo/bin`, `cargo`, and `rustup-home`) and prepend the bootstrapped
Cargo binaries to `PATH`; no host toolchain administration or sudo is used.

The pinned `cambrian/mozconfig` builds a native browser with bootstrap enabled,
debug symbols, tests, and the updater disabled. It does not select a prebuilt
artifact. Packaging records the exact source revision, native package hash,
object directory, actual compiler configuration, platform, and the used
mozconfig in `manifest.json`.

## Verification handoff

Automated wrapper tests can run without compiling Firefox:
`python3 cambrian/tests/test_launcher.py`. To manually verify a build, extract
the archive and run `./cambrian-firefox/firefox --headless about:blank`; record
the host platform and archive SHA-256. For an actual package check, use a
local HTML file and `--headless --screenshot` with a fresh `XDG_STATE_HOME`,
then inspect the screenshot and exit status. GUI execution is optional and
requires a desktop session; native Linux GTK and related shared libraries are
required because the archive is not fully static. No CI or build result is
implied by this source document.
