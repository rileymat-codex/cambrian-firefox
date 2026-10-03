"use strict";

const HOST = "host-overrides-test.invalid";
const mainThread = Services.tm.currentThread;

class Listener {
  constructor() {
    this.promise = new Promise(resolve => {
      this.resolve = resolve;
    });
  }

  onLookupComplete(request, record, status) {
    let addresses = [];
    if (record && Components.isSuccessCode(status)) {
      record.QueryInterface(Ci.nsIDNSAddrRecord);
      while (record.hasMore()) {
        addresses.push(record.getNextAddrAsString());
      }
    }
    this.resolve({ addresses, status });
  }
}
Listener.prototype.QueryInterface = ChromeUtils.generateQI(["nsIDNSListener"]);

function resolve(
  host = HOST,
  type = Ci.nsIDNSService.RESOLVE_TYPE_DEFAULT,
  flags = 0
) {
  let listener = new Listener();
  try {
    Services.dns.asyncResolve(
      host,
      type,
      flags,
      null,
      listener,
      mainThread,
      {}
    );
  } catch (error) {
    return Promise.resolve({ addresses: [], status: error.result });
  }
  return listener.promise;
}

add_setup(function setup() {
  Services.prefs.clearUserPref("network.host_overrides");
  registerCleanupFunction(() => {
    Services.prefs.clearUserPref("network.host_overrides");
    Services.dns.clearCache(false);
  });
});

add_task(async function test_normal_host_control() {
  let result = await resolve("localhost");
  Assert.equal(result.status, Cr.NS_OK);
  Assert.ok(result.addresses.length, "localhost still uses ordinary DNS");
});

add_task(async function test_synthetic_and_canonical_match() {
  Services.prefs.setCharPref(
    "network.host_overrides",
    `${HOST.toUpperCase()}=192.0.2.2`
  );
  let result = await resolve(`${HOST}.`);
  Assert.equal(result.status, Cr.NS_OK);
  Assert.deepEqual(result.addresses, ["192.0.2.2"]);
});

add_task(async function test_change_and_remove() {
  Services.prefs.setCharPref("network.host_overrides", `${HOST}=192.0.2.3`);
  Assert.deepEqual((await resolve()).addresses, ["192.0.2.3"]);

  Services.prefs.setCharPref("network.host_overrides", `${HOST}=192.0.2.4`);
  Assert.deepEqual((await resolve()).addresses, ["192.0.2.4"]);

  Services.prefs.setCharPref(
    "network.host_overrides",
    `${HOST}=192.0.2.5|insecure`
  );
  Assert.deepEqual((await resolve()).addresses, ["192.0.2.5"]);

  Services.prefs.clearUserPref("network.host_overrides");
  let result = await resolve();
  Assert.notEqual(result.status, Cr.NS_OK);
  Assert.deepEqual(result.addresses, []);
  Services.dns.clearCache(false);
});

add_task(async function test_invalid_pref_fails_closed() {
  for (let value of [
    `${HOST}=192.0.2.5,${HOST}=192.0.2.6`,
    `${HOST}=999.1.1.1`,
    `${HOST}=192.0.2.01`,
    `${HOST}=192.0.2.1234`,
    `*.${HOST}=192.0.2.7`,
    `${HOST}=2001:db8::1`,
    `${HOST}=192.0.2.8,`,
    `${HOST}=192.0.2.8, `,
  ]) {
    Services.prefs.setCharPref("network.host_overrides", value);
    let result = await resolve();
    Assert.notEqual(result.status, Cr.NS_OK, value);
    Assert.deepEqual(result.addresses, [], value);
  }
  Services.prefs.setCharPref("network.host_overrides", `${HOST}=192.0.2.9`);
  let ipv6Only = await resolve(
    HOST,
    Ci.nsIDNSService.RESOLVE_TYPE_DEFAULT,
    Ci.nsIDNSService.RESOLVE_DISABLE_IPV4
  );
  Assert.notEqual(ipv6Only.status, Cr.NS_OK);
  Assert.deepEqual(ipv6Only.addresses, []);

  let https = await resolve(HOST, Ci.nsIDNSService.RESOLVE_TYPE_HTTPSSVC);
  Assert.equal(https.status, Cr.NS_ERROR_UNKNOWN_HOST);
  Assert.deepEqual(https.addresses, []);
});
