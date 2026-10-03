#!/usr/bin/env python3
"""Stage a native mach package as a relocatable CambrianFirefox archive."""
import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import re
import shlex
from pathlib import Path

UPSTREAM_SHA = "fdd757a2e09c9471cddf383e64e631e4ce178499"

def safe_extract(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:*", errorlevel=2) as tar:
        root = destination.resolve()
        for member in tar.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"archive member escapes staging directory: {member.name}")
            if member.issym() or member.islnk():
                link = (target.parent / member.linkname).resolve()
                if link != root and root not in link.parents:
                    raise ValueError(f"archive link escapes staging directory: {member.name}")
        try:
            tar.extractall(destination, filter="data")
        except TypeError:
            tar.extractall(destination)

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def merge_policy(app: Path) -> None:
    policy_path = app / "distribution" / "policies.json"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}
    policy.setdefault("policies", {})["DisableAppUpdate"] = True
    policy["policies"].setdefault("Preferences", {})["browser.shell.checkDefaultBrowser"] = {"Value": False, "Status": "locked"}
    policy_path.write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--objdir", type=Path, required=True)
    parser.add_argument("--mozconfig", type=Path, required=True)
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    output = args.output.resolve()
    staging = output.parent / f".{output.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    extracted = staging / "extracted"
    extracted.mkdir()
    safe_extract(args.archive.resolve(), extracted)
    candidates = [path for path in extracted.iterdir() if path.is_dir()]
    if len(candidates) != 1:
        raise SystemExit(f"expected one top-level package directory, found {len(candidates)}")
    app = staging / "cambrian-firefox" / "app"
    app.parent.mkdir()
    shutil.copytree(candidates[0], app, symlinks=True)
    if not (app / "firefox").is_file():
        raise SystemExit(f"native package has no app/firefox executable: {args.archive}")
    application_ini = app / "application.ini"
    version_match = re.search(r"^Version=(.+)$", application_ini.read_text(encoding="utf-8"), re.MULTILINE)
    if not version_match or version_match.group(1).strip() != "157.0":
        raise SystemExit(f"native package application.ini is not version 157.0: {application_ini}")
    merge_policy(app)
    actual_mozconfig = args.objdir / ".mozconfig"
    if not actual_mozconfig.is_file():
        actual_mozconfig = args.mozconfig
    mozconfig_text = actual_mozconfig.read_text(encoding="utf-8")
    autoconf = args.objdir / "config" / "autoconf.mk"
    compiler = {}
    if autoconf.is_file():
        for line in autoconf.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.match(r"^(CC|CXX|RUSTC)\s*=\s*(.+)$", line)
            if match:
                compiler[match.group(1)] = match.group(2).strip()
    for name, command in list(compiler.items()):
        try:
            compiler[f"{name}_version"] = subprocess.check_output(shlex.split(command) + ["--version"], text=True, stderr=subprocess.STDOUT).splitlines()[0]
        except (OSError, subprocess.CalledProcessError, IndexError):
            compiler[f"{name}_version"] = "unavailable"
    manifest = {
        "product": "CambrianFirefox", "version": "157.0",
        "source_repository": "https://github.com/rileymat-codex/cambrian-firefox",
        "upstream_source_sha": UPSTREAM_SHA,
        "source_revision": subprocess.check_output(["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True).strip(),
        "native_package": args.archive.name, "native_package_sha256": sha256(args.archive),
        "mozconfig": {"path": str(actual_mozconfig), "sha256": hashlib.sha256(mozconfig_text.encode()).hexdigest(), "contents": mozconfig_text},
        "objdir": str(args.objdir.resolve()), "compiler": compiler,
        "build_platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "build_status": "produced by cambrian/package.sh",
    }
    bundle = staging / "cambrian-firefox"
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    shutil.copy2(source_root / "cambrian" / "README.md", bundle / "README.md")
    docs = source_root / "cambrian" / "docs"
    if docs.is_dir():
        shutil.copytree(docs, bundle / "docs")
    tests = source_root / "cambrian" / "tests"
    fixture_files = ("host_overrides_browser.py", "local_server.js", "README.md")
    if all((tests / name).is_file() for name in fixture_files):
        (bundle / "tests").mkdir()
        for name in fixture_files:
            shutil.copy2(tests / name, bundle / "tests" / name)
    launcher = source_root / "cambrian" / "firefox"
    for name in ("firefox", "cambrian-firefox"):
        target = bundle / name
        shutil.copy2(launcher, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if output.exists():
        output.unlink()
    with tarfile.open(output, "w:xz") as tar:
        tar.add(bundle, arcname="cambrian-firefox", recursive=True)
    shutil.rmtree(staging)
    print(output)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
