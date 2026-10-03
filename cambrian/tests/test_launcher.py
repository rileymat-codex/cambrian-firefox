#!/usr/bin/env python3
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def run(args, env):
    return subprocess.run([str(ROOT / "firefox"), *args], env=env, text=True, capture_output=True)

with tempfile.TemporaryDirectory(prefix="cambrian launcher ") as temp:
    temp_path = Path(temp)
    launcher = temp_path / "bundle with spaces" / "firefox"
    fake = launcher.parent / "app" / "firefox"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURE\"\n", encoding="utf-8")
    fake.chmod(0o755)
    shutil.copy2(ROOT / "firefox", launcher)
    launcher.chmod(0o755)
    env = os.environ.copy()
    env.update(HOME=str(temp_path / "home"), XDG_STATE_HOME=str(temp_path / "state"), CAPTURE=str(temp_path / "args"))
    (temp_path / "home").mkdir()
    result = subprocess.run([str(launcher), "--headless", "https://example.test/a b"], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert (temp_path / "state/cambrian-firefox/profile").stat().st_mode & 0o777 == 0o700
    assert (temp_path / "args").read_text().splitlines() == ["--no-remote", "--profile", str(temp_path / "state/cambrian-firefox/profile"), "--headless", "https://example.test/a b"]
    for option in ("-P", "-Pother", "--P", "--P=other", "-profile", "-profile=/tmp/old", "--profile=/tmp/old", "--PROFILE=/tmp/old", "-PROFILE=/tmp/old", "--ProfileManager"):
        rejected = subprocess.run([str(launcher), option], env=env, text=True, capture_output=True)
        assert rejected.returncode == 2, (option, rejected.stderr)
    passed = subprocess.run([str(launcher), "--private-window", "about:blank"], env=env, text=True, capture_output=True)
    assert passed.returncode == 0, passed.stderr
    home_only_env = env.copy()
    home_only_env.pop("XDG_STATE_HOME")
    home_only = subprocess.run([str(launcher), "--headless", "about:blank"], env=home_only_env, text=True, capture_output=True)
    assert home_only.returncode == 0, home_only.stderr
    assert (temp_path / "home/.local/state/cambrian-firefox/profile").is_dir()
print("launcher tests passed")
