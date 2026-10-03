#!/usr/bin/env node
const fs = require("fs");
const http = require("http");
const https = require("https");
const http2 = require("http2");
const tls = require("tls");
const crypto = require("crypto");

const [certDir, output] = process.argv.slice(2);
const key = fs.readFileSync(`${certDir}/server.key`);
const cert = fs.readFileSync(`${certDir}/server.crt`);
const badKey = fs.readFileSync(`${certDir}/bad.key`);
const badCert = fs.readFileSync(`${certDir}/bad.crt`);
const alpn = ["h2", "http/1.1"];
let nextConnection = 0;
const records = [];
function writeReport(ports) {
  fs.writeFileSync(output, JSON.stringify({...ports, records}));
}

function record(req, protocol) {
  const socket = req.socket;
  const item = {
    timestamp: Date.now(),
    id: socket.__connectionId || (socket.__connectionId = ++nextConnection),
    protocol,
    host: req.headers[":authority"] || req.headers.host || "",
    origin: req.headers.origin || "",
    cookie: req.headers.cookie || "",
    path: req.url,
    remoteAddress: socket.remoteAddress,
    localAddress: socket.localAddress,
    localPort: socket.localPort,
    sni: socket.servername || "",
    alpn: socket.alpnProtocol || "",
    sessionReused: socket.isSessionReused ? socket.isSessionReused() : false,
  };
  records.push(item);
  if (globalThis.serverPorts) writeReport(globalThis.serverPorts);
  return item;
}

function response(req, res, protocol) {
  const item = record(req, protocol);
  res.setHeader("cache-control", "no-store");
  if (req.url !== "/cors-deny") {
    res.setHeader("access-control-allow-origin", req.headers.origin || "*");
    res.setHeader("access-control-allow-credentials", "true");
  }
  if (req.url === "/page") {
    res.setHeader("content-type", "text/html");
    res.end("<!doctype html><title>host override</title><p>host override</p>");
    return;
  }
  if (req.url === "/cookie") {
    res.setHeader("set-cookie", "host_override_cookie=present; Path=/");
  }
  if (req.url === "/hsts") {
    res.setHeader("strict-transport-security", "max-age=90");
    res.setHeader("content-type", "text/html");
    res.end("<!doctype html><title>host override hsts</title><p>HSTS fixture</p>");
    return;
  }
  if (req.url === "/resumption") {
    res.setHeader("connection", "close");
  }
  if (req.url === "/redirect") {
    res.writeHead(302, {location: "/json"});
    res.end();
    return;
  }
  if (req.url === "/alt-svc") {
    res.setHeader("alt-svc", `h2="alt-test.invalid:${globalThis.trapPort}"; ma=60, h3="alt-test.invalid:${globalThis.trapPort}"; ma=60`);
  }
  res.setHeader("content-type", "application/json");
  res.end(JSON.stringify(item));
}

function upgrade(req, socket) {
  const keyHeader = req.headers["sec-websocket-key"];
  if (!keyHeader) return socket.destroy();
  const item = record(req, socket.encrypted ? "wss" : "ws");
  const accept = crypto.createHash("sha1").update(keyHeader + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest("base64");
  socket.write("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + accept + "\r\n\r\n");
  socket.on("data", data => {
    if (data.length < 2) return;
    const length = data[1] & 0x7f;
    const offset = length < 126 ? 2 : 4;
    const mask = data.subarray(offset, offset + 4);
    const payloadStart = offset + 4;
    const payload = Buffer.alloc(length);
    for (let i = 0; i < length; i++) payload[i] = data[payloadStart + i] ^ mask[i % 4];
    const out = Buffer.alloc(length + 2);
    out[0] = 0x81; out[1] = length;
    payload.copy(out, 2); socket.write(out);
  });
  records.push({...item, websocket: true});
}

const h1 = http.createServer((req, res) => response(req, res, "http/1.1"));
h1.on("upgrade", upgrade);
const tls1 = https.createServer({key, cert, ALPNProtocols: ["http/1.1"]}, (req, res) => response(req, res, "http/1.1"));
const h2 = httpsServer(true);
tls1.on("upgrade", upgrade);
const ordinary = http.createServer((req, res) => response(req, res, "http/1.1"));
const badTls = https.createServer({key: badKey, cert: badCert, ALPNProtocols: ["http/1.1"]}, (req, res) => response(req, res, "http/1.1"));
const badOrdinaryTls = https.createServer({key: badKey, cert: badCert, ALPNProtocols: ["http/1.1"]}, (req, res) => response(req, res, "http/1.1"));
const ordinaryTls = https.createServer({key, cert, ALPNProtocols: ["http/1.1"]}, (req, res) => response(req, res, "http/1.1"));
const trap = httpsServer(true);
for (const server of [badTls, badOrdinaryTls]) {
  server.on("tlsClientError", (error, socket) => {
    records.push({event: "tlsClientError", timestamp: Date.now(), code: error.code || "", message: error.message, localAddress: socket.localAddress, localPort: socket.localPort, sni: socket.servername || ""});
    if (globalThis.serverPorts) writeReport(globalThis.serverPorts);
  });
}
trap.on("secureConnection", socket => {
  records.push({event: "secureConnection", protocol: "tls", localAddress: socket.localAddress, localPort: socket.localPort, sni: socket.servername || ""});
  if (globalThis.serverPorts) writeReport(globalThis.serverPorts);
});
function httpsServer(http2Only) {
  const options = {key, cert, allowHTTP1: false, ALPNProtocols: ["h2"]};
  const server = http2.createSecureServer(options);
  server.on("request", (req, res) => response(req, res, "h2"));
  server.on("sessionError", () => {});
  return server;
}

Promise.all([listen(h1), listen(tls1), listen(h2)]).then(ports => {
  return Promise.all([listen(ordinary, "127.0.0.1", ports[0]), listen(badTls)]).then(extra => Promise.all([listen(badOrdinaryTls, "127.0.0.1", extra[1]), listen(ordinaryTls, "127.0.0.1", ports[1]), listen(trap, "127.0.0.1")]).then(more => ({ports, bad: extra[1], ordinaryTls: more[1], trap: more[2]})));
}).then(ports => {
  const mapped = ports.ports;
  globalThis.trapPort = ports.trap;
  const result = {http: mapped[0], https: mapped[1], h2: mapped[2], ordinary: mapped[0], badHttps: ports.bad, ordinaryHttps: ports.ordinaryTls, trap: ports.trap};
  globalThis.serverPorts = result;
  writeReport(result);
  console.log(JSON.stringify(result));
});
function listen(server, host = "127.0.0.2", port = 0) {
  return new Promise(resolve => server.listen(port, host, () => resolve(server.address().port)));
}
process.on("SIGTERM", () => { if (globalThis.serverPorts) writeReport(globalThis.serverPorts); process.exit(0); });
