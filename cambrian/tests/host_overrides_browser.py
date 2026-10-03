#!/usr/bin/env python3
"""Local real-browser host override harness.

Requires only Python's standard library, Node.js, openssl, and a Firefox binary.
The pref string is intentionally supplied by the caller while its final name is
being integrated.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import glob


class Marionette:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.sock.settimeout(30)
        self.ident = 0
        self._read_frame()

    def _read(self, n):
        value = b""
        while len(value) < n:
            part = self.sock.recv(n - len(value))
            if not part:
                raise RuntimeError("Marionette connection closed")
            value += part
        return value

    def command(self, name, params=None):
        self.ident += 1
        body = json.dumps([0, self.ident, name, params or {}]).encode()
        self.sock.sendall(str(len(body)).encode() + b":" + body)
        message = self._read_frame()
        if message[0] != 1 or message[2]:
            raise RuntimeError(f"Marionette {name}: {message[2]}")
        return message[3]

    def _read_frame(self):
        length = b""
        while True:
            char = self._read(1)
            if char == b":":
                break
            length += char
        return json.loads(self._read(int(length)))

    def close(self):
        try:
            self.command("WebDriver:DeleteSession")
        except Exception:
            pass
        self.sock.close()


def reserve_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def wait_port(port, process):
    deadline = time.time() + 30
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Firefox exited with {process.returncode}")
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=1)
            sock.close()
            return
        except OSError:
            time.sleep(.1)
    raise TimeoutError("Timed out waiting for Marionette")


def make_certs(directory):
    run = lambda args: subprocess.run(args, cwd=directory, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=host-override-test-ca", "-keyout", "ca.key", "-out", "ca.crt"])
    Path(directory, "san.cnf").write_text("subjectAltName=DNS:dev-test.invalid,DNS:redirect.invalid,DNS:ordinary.invalid,DNS:localhost,DNS:hsts-test.invalid,DNS:dns-proof.invalid,DNS:alt-test.invalid\n", encoding="utf-8")
    run(["openssl", "req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=dev-test.invalid", "-keyout", "server.key", "-out", "server.csr"])
    run(["openssl", "x509", "-req", "-days", "2", "-in", "server.csr", "-CA", "ca.crt", "-CAkey", "ca.key", "-CAcreateserial", "-out", "server.crt", "-extfile", "san.cnf"])
    run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=untrusted-host-override", "-keyout", "bad.key", "-out", "bad.crt"])


def chrome_import(m, ca):
    pem = Path(ca).read_text(encoding="ascii")
    encoded = "".join(pem.splitlines()[1:-1])
    m.command("Marionette:SetContext", {"value": "chrome"})
    script = """
      const cert = arguments[0];
      const db = Components.classes['@mozilla.org/security/x509certdb;1']
        .getService(Components.interfaces.nsIX509CertDB);
      db.addCertFromBase64(cert, 'CT,,');
      return true;
    """
    m.command("WebDriver:ExecuteScript", {"script": script, "args": [encoded], "newSandbox": True})
    m.command("Marionette:SetContext", {"value": "content"})


def chrome_pref(m, name, value):
    m.command("Marionette:SetContext", {"value": "chrome"})
    script = """const prefs = Components.classes['@mozilla.org/preferences-service;1'].getService(Components.interfaces.nsIPrefBranch); prefs.setCharPref(arguments[0], arguments[1]); return true;"""
    m.command("WebDriver:ExecuteScript", {"script": script, "args": [name, value], "newSandbox": True})
    m.command("Marionette:SetContext", {"value": "content"})


def chrome_bool_pref(m, name, value):
    m.command("Marionette:SetContext", {"value": "chrome"})
    content(m, "Components.classes['@mozilla.org/preferences-service;1'].getService(Components.interfaces.nsIPrefBranch).setBoolPref(arguments[0],arguments[1]); return true;", [name, value])
    m.command("Marionette:SetContext", {"value": "content"})


def chrome_int_pref(m, name, value):
    m.command("Marionette:SetContext", {"value": "chrome"})
    script = """const prefs = Components.classes['@mozilla.org/preferences-service;1'].getService(Components.interfaces.nsIPrefBranch); prefs.setIntPref(arguments[0], arguments[1]); return true;"""
    m.command("WebDriver:ExecuteScript", {"script": script, "args": [name, value], "newSandbox": True})
    m.command("Marionette:SetContext", {"value": "content"})


def content(m, script, args=None):
    result = m.command("WebDriver:ExecuteScript", {"script": script, "args": args or [], "newSandbox": True})
    return result.get("value")


def check_result(check, records, baseline):
    result_obj = check.get("result") if isinstance(check.get("result"), dict) else {}
    if check["name"] == "process-path":
        return bool(result_obj.get("launched")) == (check["expected"] == "on") and (check["expected"] != "on" or result_obj.get("pid", 0) > 0)
    if check["name"] == "untrusted-navigation-insecure":
        return result_obj.get("title") == "host override" and result_obj.get("origin") == check["url"].rsplit("/", 1)[0] and result_obj.get("location") == check["url"]
    if check["name"].startswith("indicator-"):
        if check["name"] == "indicator-ordinary":
            return result_obj.get("hidden") is True
        return result_obj.get("hidden") is False and result_obj.get("visible") is True and "dev-test.invalid" in result_obj.get("value", "") and "127.0.0.2" in result_obj.get("value", "") and result_obj.get("insecure") == (check["name"] == "indicator-insecure") and (check["name"] != "indicator-insecure" or "TLS bypass" in result_obj["value"])
    if check["name"] == "dns-records":
        values = check.get("result", [])
        return len(values) == 2 and values[0]["status"] == 0 and values[0]["addresses"] == ["127.0.0.2"] and values[1]["status"] != 0 and not values[1]["addresses"]
    if check["name"] == "dns-log":
        return result_obj.get("synthetic") and result_obj.get("suppressed") and not result_obj.get("realLookup")
    if check["name"] == "proxy-rejection":
        return baseline or (result_obj.get("ok") is False and not any(r.get("path", "").startswith("http://dev-test.invalid:") for r in records))
    if check["name"] == "proxy-control":
        return result_obj.get("ok") is True and any(r.get("path", "").startswith("http://localhost:") for r in records)
    if baseline and check["name"] in {"untrusted-tls-normal", "untrusted-tls-insecure", "untrusted-tls-mode-off", "untrusted-tls-ordinary", "hsts-insecure-reject", "mapping-change-local", "mapping-removed", "mapping-readded", "mapping-stateful", "altsvc", "altsvc-trap", "tls-resumption", "tls-resumption-mode-off"}:
        return True
    if check["name"] == "cookie-persistence":
        result = check.get("result", {})
        return (not baseline and "host_override_cookie=present" in result.get("serverCookie", "") and "host_override_cookie=present" in result.get("browserCookie", "")) or (baseline and "error" in result)
    if check["name"] == "cors-matrix":
        result = check.get("result", [])
        return (not baseline and result == [True, False]) or (baseline and (not result or "error" in result))
    if check["name"] in ("mapped-ws", "mapped-wss"):
        result = check.get("result", {})
        if baseline:
            return result.get("ok") is not True
        expected_protocol = "wss" if check["name"] == "mapped-wss" else "ws"
        authority = check["url"].split("://", 1)[1].split("/", 1)[0]
        return result.get("ok") is True and result.get("browserOrigin", "").startswith("http://dev-test.invalid:") and any(r.get("protocol") == expected_protocol and r.get("sni") == ("dev-test.invalid" if expected_protocol == "wss" else "") and r.get("localAddress") == "127.0.0.2" and r.get("host") == authority and r.get("origin") == result["browserOrigin"] for r in records)
    if check["name"] in ("untrusted-tls-normal", "untrusted-tls-mode-off", "untrusted-tls-ordinary", "hsts-insecure-reject", "mapping-removed"):
        if check["name"] == "mapping-removed":
            return not result_obj.get("ok", False)
        try:
            port = int(check["url"].rsplit(":", 1)[1].split("/", 1)[0])
        except (ValueError, IndexError):
            return False
        tls_error = any(r.get("event") == "tlsClientError" and r.get("localPort") == port and r.get("timestamp", 0) >= result_obj.get("startedAtMs", 0) and r.get("timestamp", 0) <= result_obj.get("endedAtMs", float("inf")) and r.get("sni") == check["url"].split("://", 1)[1].split(":", 1)[0] for r in records)
        return not result_obj.get("ok", False) and tls_error
    if check["name"] == "untrusted-tls-insecure":
        return check.get("result", {}).get("ok") is True
    if check["name"] == "mapping-change-local":
        try:
            return json.loads(check["result"]["text"])["localAddress"] == "127.0.0.1"
        except (KeyError, TypeError, json.JSONDecodeError):
            return False
    if check["name"] == "mapping-readded":
        try:
            return json.loads(check["result"]["text"])["localAddress"] == "127.0.0.2"
        except (KeyError, TypeError, json.JSONDecodeError):
            return False
    if check["name"] == "mapping-stateful":
        return False
    if check["name"] == "altsvc":
        return check.get("result", {}).get("ok") is True and not any(r.get("protocol") == "h3" for r in records)
    if check["name"] == "altsvc-trap":
        return not any(r.get("localAddress") == "127.0.0.1" and r.get("localPort") == check.get("trap") for r in records)
    if check["name"] == "tls-resumption":
        port = int(check["url"].rsplit(":", 1)[1].split("/", 1)[0])
        return check.get("result", {}).get("ok") is True and check["result"].get("count") == 3 and any(r.get("sessionReused") is True and r.get("localPort") == port and r.get("timestamp", 0) >= result_obj.get("startedAtMs", 0) and r.get("timestamp", 0) <= result_obj.get("endedAtMs", float("inf")) and r.get("sni") == check["url"].split("://", 1)[1].split(":", 1)[0] for r in records)
    if check["name"] == "tls-resumption-mode-off":
        port = int(check["url"].rsplit(":", 1)[1].split("/", 1)[0])
        return check.get("result", {}).get("ok") is False and any(r.get("event") == "tlsClientError" and r.get("localPort") == port and r.get("timestamp", 0) >= result_obj.get("startedAtMs", 0) and r.get("timestamp", 0) <= result_obj.get("endedAtMs", float("inf")) and r.get("sni") == check["url"].split("://", 1)[1].split(":", 1)[0] for r in records)
    mapped = check["name"] not in {"ordinary-host", "ordinary-https"}
    result_obj = check.get("result") if isinstance(check.get("result"), dict) else {}
    ok = bool(result_obj.get("ok"))
    if not baseline and mapped and ok and check["name"] not in {"mapped-ws", "mapped-wss"}:
        location = result_obj.get("location", "")
        if "dev-test.invalid:" not in location:
            return False
    if baseline:
        return ok is False if mapped else ok
    if mapped and not ok:
        return False
    if not mapped and not ok:
        return False
    try:
        payload = json.loads(check["result"]["text"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return check["name"] == "mapped-ws" and ok
    if check["name"] == "redirect" and (not result_obj.get("redirected") or result_obj.get("responseURL") != check["url"].replace("/redirect", "/json")):
        return False
    if mapped:
        expected_protocol = "h2" if check["name"] == "mapped-h2" else ("http/1.1" if check["name"] == "mapped-https" else payload.get("protocol"))
        return payload["localAddress"] == "127.0.0.2" and check["url"].split("://", 1)[1].split("/", 1)[0] == payload["host"] and (check["name"] not in {"mapped-https", "mapped-h2"} or payload.get("sni") == "dev-test.invalid") and payload.get("protocol") == expected_protocol
    return payload["localAddress"] == "127.0.0.1" and (check["name"] != "ordinary-https" or (payload.get("sni") == "localhost" and payload.get("protocol") == "http/1.1"))


def probe(marionette, url):
    started = int(time.time() * 1000)
    script = """return fetch(arguments[0], {redirect:'follow', credentials:'include'}).then(r => r.text()).then(text => ({ok:true,text})).catch(e => ({ok:false,error:String(e)}));"""
    result = content(marionette, script, [url])
    result["startedAtMs"] = started
    time.sleep(.05)
    result["endedAtMs"] = int(time.time() * 1000)
    return result


def indicator(marionette):
    marionette.command("Marionette:SetContext", {"value": "chrome"})
    value = content(marionette, "const el = document.getElementById('host-override-indicator'); if (!el) return null; const rect = el.getBoundingClientRect(); const style = getComputedStyle(el); return {hidden:el.hidden,value:el.value,insecure:el.hasAttribute('insecure'),visible:rect.width>0 && rect.height>0 && style.display!='none' && style.visibility=='visible'};")
    marionette.command("Marionette:SetContext", {"value": "content"})
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--firefox", required=True)
    parser.add_argument("--overrides", default="dev-test.invalid=127.0.0.2")
    parser.add_argument("--report", required=True)
    parser.add_argument("--baseline", action="store_true", help="expect mapped cases to fail")
    parser.add_argument("--socket-process", choices=("on", "off"), default="on")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    results = {"firefox": args.firefox, "overrides": args.overrides, "baseline": args.baseline, "checks": [], "setup": {}}
    marionette_port = reserve_port()
    with tempfile.TemporaryDirectory(prefix="host-overrides-") as temp:
        temp = Path(temp)
        make_certs(temp)
        server_report = temp / "server.json"
        server = subprocess.Popen(["node", str(root / "local_server.js"), str(temp), str(server_report)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            line = server.stdout.readline()
            if not line:
                raise RuntimeError(server.stderr.read())
            ports = json.loads(line)
            results["setup"]["ports"] = ports
            profile = temp / "profile"
            profile.mkdir()
            initial_overrides = args.overrides
            if "dns-proof.invalid=" not in initial_overrides:
                initial_overrides += ",dns-proof.invalid=127.0.0.2"
            (profile / "user.js").write_text(f"user_pref('marionette.port', {marionette_port});\n" + f"user_pref('network.host_overrides', {json.dumps(initial_overrides)});\n", encoding="utf-8")
            with (profile / "user.js").open("a") as prefs:
                prefs.write("user_pref('network.process.enabled', " + ("true" if args.socket_process == "on" else "false") + ");\n")
            results["setup"]["socketProcessRequested"] = args.socket_process
            log = temp / "firefox.log"
            env = os.environ.copy()
            env["MOZ_LOG"] = "nsHostResolver:5,nsHttp:3"
            env["MOZ_LOG_FILE"] = str(log)
            browser = subprocess.Popen([args.firefox, "--headless", "--marionette", "--marionette-port", str(marionette_port), "--remote-allow-system-access", "--profile", str(profile), "about:blank"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                wait_port(marionette_port, browser)
                marionette = Marionette("127.0.0.1", marionette_port)
                session_caps = marionette.command("WebDriver:NewSession", {"capabilities": {"alwaysMatch": {"acceptInsecureCerts": False}}})
                results["setup"]["acceptInsecureCerts"] = session_caps.get("capabilities", {}).get("acceptInsecureCerts")
                chrome_import(marionette, temp / "ca.crt")
                if not args.baseline:
                    chrome_int_pref(marionette, "network.trr.mode", 3)
                    marionette.command("Marionette:SetContext", {"value": "chrome"})
                    dns_script = """const dns = Components.classes['@mozilla.org/network/dns-service;1'].getService(Components.interfaces.nsIDNSService);
                    const thread = Components.classes['@mozilla.org/thread-manager;1'].getService(Components.interfaces.nsIThreadManager).currentThread;
                    return Promise.all([0,65].map(type => new Promise(resolve => {
                      const listener = { QueryInterface: ChromeUtils.generateQI(['nsIDNSListener']), onLookupComplete(req, record, status) {
                        const addresses = []; if (Components.isSuccessCode(status)) { record.QueryInterface(Components.interfaces.nsIDNSAddrRecord); while (record.hasMore()) addresses.push(record.getNextAddrAsString()); }
                        resolve({type,status,addresses}); } };
                      try { dns.asyncResolve('dns-proof.invalid', type, 0, null, listener, thread, {}); } catch(e) { resolve({type,status:e.result,addresses:[]}); }
                    })));"""
                    dns_result = content(marionette, dns_script)
                    results["checks"].append({"name": "dns-records", "result": dns_result})
                    marionette.command("Marionette:SetContext", {"value": "content"})
                    chrome_int_pref(marionette, "network.trr.mode", 0)
                checks = [
                    ("mapped-http", f"http://dev-test.invalid:{ports['http']}/json"),
                    ("mapped-https", f"https://dev-test.invalid:{ports['https']}/json"),
                    ("mapped-h2", f"https://dev-test.invalid:{ports['h2']}/json"),
                    ("ordinary-https", f"https://localhost:{ports['ordinaryHttps']}/json"),
                    ("redirect", f"http://dev-test.invalid:{ports['http']}/redirect"),
                    ("cookie", f"http://dev-test.invalid:{ports['http']}/cookie"),
                    ("ordinary-host", f"http://localhost:{ports['ordinary']}/json"),
                    ("cors-deny", f"http://dev-test.invalid:{ports['http']}/cors-deny"),
                ]
                script = """return fetch(arguments[0], {redirect:'follow', credentials:'include'}).then(async r => ({ok:true,text:await r.text(),responseURL:r.url,redirected:r.redirected})).catch(e => ({ok:false,error:String(e)}));"""
                for name, url in checks:
                    value = None
                    error = None
                    try:
                        marionette.command("WebDriver:Navigate", {"url": url.rsplit("/", 1)[0] + "/page"})
                        value = content(marionette, script, [url])
                        value["location"] = marionette.command("WebDriver:GetCurrentURL").get("value")
                    except Exception as exc:
                        error = str(exc)
                    results["checks"].append({"name": name, "url": url, "result": value, "error": error})
                    if not args.baseline and name in {"mapped-https", "ordinary-https"}:
                        results["checks"].append({"name": "indicator-ordinary" if name == "ordinary-https" else "indicator-normal", "result": indicator(marionette)})
                if not args.baseline:
                    bad_url = f"https://dev-test.invalid:{ports['badHttps']}/json"
                    if not args.baseline:
                        chrome_pref(marionette, "network.host_overrides", "dev-test.invalid=127.0.0.2,dns-proof.invalid=127.0.0.2")
                    try:
                        results["checks"].append({"name": "untrusted-tls-normal", "url": bad_url, "result": probe(marionette, bad_url)})
                        chrome_pref(marionette, "network.host_overrides", "dev-test.invalid=127.0.0.2|insecure,dns-proof.invalid=127.0.0.2")
                        results["checks"].append({"name": "untrusted-tls-insecure", "url": bad_url, "result": probe(marionette, bad_url)})
                        insecure_page = bad_url.rsplit("/", 1)[0] + "/page"
                        marionette.command("WebDriver:Navigate", {"url": insecure_page})
                        results["checks"].append({"name": "untrusted-navigation-insecure", "url": insecure_page, "result": content(marionette, "return {title:document.title,origin:location.origin,location:location.href};")})
                        if not args.baseline:
                            results["checks"].append({"name": "indicator-insecure", "result": indicator(marionette)})
                        chrome_pref(marionette, "network.host_overrides", "dev-test.invalid=127.0.0.2,dns-proof.invalid=127.0.0.2")
                        results["checks"].append({"name": "untrusted-tls-mode-off", "url": bad_url, "result": probe(marionette, bad_url)})
                        results["checks"].append({"name": "untrusted-tls-ordinary", "url": f"https://localhost:{ports['badHttps']}/json", "result": probe(marionette, f"https://localhost:{ports['badHttps']}/json")})
                        chrome_pref(marionette, "network.host_overrides", "dev-test.invalid=127.0.0.2,dns-proof.invalid=127.0.0.2,hsts-test.invalid=127.0.0.2")
                        hsts_url = f"https://hsts-test.invalid:{ports['https']}/hsts"
                        marionette.command("WebDriver:Navigate", {"url": hsts_url})
                        chrome_pref(marionette, "network.host_overrides", "dev-test.invalid=127.0.0.2,dns-proof.invalid=127.0.0.2,hsts-test.invalid=127.0.0.2|insecure")
                        bad_hsts_url = f"https://hsts-test.invalid:{ports['badHttps']}/json"
                        results["checks"].append({"name": "hsts-insecure-reject", "url": bad_hsts_url, "result": probe(marionette, bad_hsts_url)})
                    except Exception as exc:
                        results["checks"].extend({"name": n, "url": bad_url, "result": {"ok": False, "error": str(exc)}} for n in ("untrusted-tls-normal", "untrusted-tls-insecure", "untrusted-tls-mode-off", "untrusted-tls-ordinary"))
                    mapped_http = f"http://dev-test.invalid:{ports['http']}/json"
                    if not args.baseline:
                        marionette.command("WebDriver:Navigate", {"url": f"http://dev-test.invalid:{ports['http']}/page"})
                    try:
                        chrome_pref(marionette, "network.host_overrides", "dev-test.invalid=127.0.0.1,dns-proof.invalid=127.0.0.2")
                        results["checks"].append({"name": "mapping-change-local", "url": mapped_http, "result": probe(marionette, mapped_http)})
                        chrome_pref(marionette, "network.host_overrides", "dns-proof.invalid=127.0.0.2")
                        results["checks"].append({"name": "mapping-removed", "url": mapped_http, "result": probe(marionette, mapped_http)})
                        chrome_pref(marionette, "network.host_overrides", "dev-test.invalid=127.0.0.2,dns-proof.invalid=127.0.0.2")
                        results["checks"].append({"name": "mapping-readded", "url": mapped_http, "result": probe(marionette, mapped_http)})
                    except Exception as exc:
                        results["checks"].append({"name": "mapping-stateful", "url": mapped_http, "result": {"ok": False, "error": str(exc)}})
                    try:
                        chrome_pref(marionette, "network.host_overrides", "dev-test.invalid=127.0.0.2,alt-test.invalid=127.0.0.1,dns-proof.invalid=127.0.0.2")
                        alt_url = f"https://dev-test.invalid:{ports['h2']}/alt-svc"
                        results["checks"].append({"name": "altsvc", "url": alt_url, "result": probe(marionette, alt_url)})
                        results["checks"].append({"name": "altsvc-trap", "url": f"https://alt-test.invalid:{ports['trap']}/json", "trap": ports['trap'], "result": probe(marionette, alt_url)})
                    except Exception as exc:
                        results["checks"].append({"name": "altsvc", "url": "", "result": {"ok": False, "error": str(exc)}})
                    try:
                        proxy_port = ports["ordinary"]
                        chrome_bool_pref(marionette, "network.proxy.allow_hijacking_localhost", True)
                        chrome_pref(marionette, "network.proxy.no_proxies_on", "")
                        chrome_pref(marionette, "network.proxy.http", "127.0.0.1")
                        chrome_int_pref(marionette, "network.proxy.http_port", proxy_port)
                        chrome_int_pref(marionette, "network.proxy.type", 1)
                        results["checks"].append({"name": "proxy-rejection", "url": mapped_http, "result": probe(marionette, mapped_http)})
                        control_url = f"http://localhost:{ports['ordinary']}/json"
                        results["checks"].append({"name": "proxy-control", "url": control_url, "result": probe(marionette, control_url)})
                        chrome_int_pref(marionette, "network.proxy.type", 0)
                    except Exception as exc:
                        results["checks"].append({"name": "proxy-rejection", "url": mapped_http, "result": {"ok": False, "error": str(exc)}})
                    try:
                        chrome_pref(marionette, "network.host_overrides", "dev-test.invalid=127.0.0.2|insecure,dns-proof.invalid=127.0.0.2")
                        resumption_url = f"https://dev-test.invalid:{ports['badHttps']}/resumption"
                        resume_script = """return (async () => { const x = []; for (let i = 0; i < 3; ++i) { x.push(await fetch(arguments[0], {cache:'no-store'}).then(r => r.json())); await new Promise(r => setTimeout(r, 150)); } return {ok:true,count:x.length}; })().catch(e => ({ok:false,error:String(e)}));"""
                        started = int(time.time() * 1000)
                        resumed = content(marionette, resume_script, [resumption_url])
                        resumed["startedAtMs"] = started
                        results["checks"].append({"name": "tls-resumption", "url": resumption_url, "result": resumed})
                        chrome_pref(marionette, "network.host_overrides", "dev-test.invalid=127.0.0.2,dns-proof.invalid=127.0.0.2")
                        results["checks"].append({"name": "tls-resumption-mode-off", "url": resumption_url, "result": probe(marionette, resumption_url)})
                    except Exception as exc:
                        results["checks"].append({"name": "tls-resumption", "url": "", "result": {"ok": False, "error": str(exc)}})
                    ws_url = f"ws://dev-test.invalid:{ports['http']}/socket"
                    ws_script = """return new Promise(resolve => { const w = new WebSocket(arguments[0]); const timer = setTimeout(() => resolve({ok:false,error:'timeout'}), 5000); w.onopen = () => w.send('probe'); w.onmessage = e => { clearTimeout(timer); resolve({ok:e.data === 'probe', data:e.data}); w.close(); }; w.onerror = () => { clearTimeout(timer); resolve({ok:false,error:'websocket'}); }; });"""
                    try:
                        ws_result = content(marionette, ws_script, [ws_url])
                        ws_result["browserOrigin"] = content(marionette, "return location.origin;")
                    except Exception as exc:
                        ws_result = {"ok": False, "error": str(exc)}
                    results["checks"].append({"name": "mapped-ws", "url": ws_url, "result": ws_result})
                    wss_url = f"wss://dev-test.invalid:{ports['https']}/socket"
                    try:
                        wss_result = content(marionette, ws_script, [wss_url])
                        wss_result["browserOrigin"] = content(marionette, "return location.origin;")
                    except Exception as exc:
                        wss_result = {"ok": False, "error": str(exc)}
                    results["checks"].append({"name": "mapped-wss", "url": wss_url, "result": wss_result})
                    try:
                        marionette.command("WebDriver:Navigate", {"url": f"http://dev-test.invalid:{ports['http']}/page"})
                        cookie_script = """return fetch(arguments[0], {credentials:'include'}).then(() => fetch(arguments[1], {credentials:'include'})).then(r => r.json()).then(x => ({serverCookie:x.cookie, browserCookie:document.cookie})).catch(e => ({error:String(e)}));"""
                        cookie_result = content(marionette, cookie_script, [f"http://dev-test.invalid:{ports['http']}/cookie", f"http://dev-test.invalid:{ports['http']}/json"])
                        results["checks"].append({"name": "cookie-persistence", "url": f"http://dev-test.invalid:{ports['http']}/cookie", "result": cookie_result})
                        cors_script = """return Promise.all([fetch(arguments[0]).then(r => r.json()).then(() => true).catch(() => false), fetch(arguments[1]).then(() => true).catch(() => false)]);"""
                        cors_result = content(marionette, cors_script, [f"http://dev-test.invalid:{ports['http']}/json", f"http://localhost:{ports['ordinary']}/cors-deny"])
                        results["checks"].append({"name": "cors-matrix", "url": "same-origin-and-cross-origin", "result": cors_result})
                    except Exception as exc:
                        results["checks"].extend([{"name": "cookie-persistence", "url": "", "result": {"ok": False, "error": str(exc)}}, {"name": "cors-matrix", "url": "", "result": {"ok": False, "error": str(exc)}}])
                if not args.baseline:
                    marionette.command("Marionette:SetContext", {"value": "chrome"})
                    process_info = content(marionette, "const io = Components.classes['@mozilla.org/network/io-service;1'].getService(Components.interfaces.nsIIOService); return {launched:io.socketProcessLaunched,pid:io.socketProcessId};")
                    results["checks"].append({"name": "process-path", "expected": args.socket_process, "result": process_info})
                    marionette.command("Marionette:SetContext", {"value": "content"})
            finally:
                if "marionette" in locals():
                    marionette.close()
                browser.terminate()
                browser.wait(timeout=10)
            log_files = glob.glob(str(log) + "*")
            results["setup"]["logs"] = log_files
            server.terminate()
            server.wait(timeout=5)
            results["setup"]["server"] = json.loads(server_report.read_text())
            if not args.baseline:
                lines = [line for file in log_files for line in Path(file).read_text(errors="replace").splitlines() if "dns-proof.invalid" in line]
                results["checks"].append({"name": "dns-log", "result": {
                    "synthetic": any("HostOverride synthetic" in line for line in lines),
                    "suppressed": any("HostOverride suppress" in line for line in lines),
                    "realLookup": [line for line in lines if "NameLookup" in line or "GetAddrInfo" in line or "TRR::" in line],
                    "evidence": lines,
                }})
            for index, log_file in enumerate(log_files):
                shutil.copy2(log_file, Path(args.report).with_suffix(f".{index}.mozlog"))
        finally:
            server.terminate()
            server.wait(timeout=5)
    Path(args.report).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    records = results["setup"]["server"]["records"]
    for check in results["checks"]:
        check["passed"] = check_result(check, records, args.baseline)
    results["passed"] = all(check["passed"] for check in results["checks"])
    Path(args.report).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0 if results["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
