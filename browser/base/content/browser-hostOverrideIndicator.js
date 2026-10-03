/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* import-globals-from browser.js */

var HostOverrideIndicator = {
  _initialized: false,

  init() {
    if (this._initialized) {
      return;
    }
    this._initialized = true;
    gBrowser.addTabsProgressListener(this);
    gBrowser.tabContainer.addEventListener("TabSelect", this);
    Services.prefs.addObserver("network.host_overrides", this);
    this.update(gBrowser.currentURI);
  },

  uninit() {
    if (!this._initialized) {
      return;
    }
    this._initialized = false;
    gBrowser.removeTabsProgressListener(this);
    gBrowser.tabContainer.removeEventListener("TabSelect", this);
    Services.prefs.removeObserver("network.host_overrides", this);
  },

  handleEvent(event) {
    if (event.type == "TabSelect") {
      this.update(gBrowser.currentURI);
    }
  },

  onLocationChange(browser, webProgress, request, locationURI) {
    if (browser == gBrowser.selectedBrowser && webProgress.isTopLevel) {
      this.update(locationURI);
    }
  },

  observe(subject, topic) {
    if (topic == "nsPref:changed") {
      this.update(gBrowser.currentURI);
    }
  },

  update(uri) {
    let label = document.getElementById("host-override-indicator");
    if (!label) {
      return;
    }

    label.hidden = true;
    label.removeAttribute("insecure");
    if (!uri || (!uri.schemeIs("http") && !uri.schemeIs("https"))) {
      return;
    }

    let host = uri.asciiHost;
    let override = Services.dns.getHostOverride(host);
    if (!override) {
      return;
    }

    let insecure = override.endsWith("|insecure");
    let address = insecure ? override.slice(0, -"|insecure".length) : override;
    label.value = insecure
      ? `⚠ TLS bypass: ${uri.host} → ${address}`
      : `${uri.host} → ${address}`;
    label.tooltipText = insecure
      ? `Host override active: ${uri.host} → ${address}; TLS verification bypass configured (HSTS may still reject)`
      : `Host override active: ${uri.host} → ${address}`;
    if (insecure) {
      label.setAttribute("insecure", "true");
    }
    label.hidden = false;
  },
};

window.addEventListener(
  "load",
  () => Services.tm.dispatchToMainThread(() => HostOverrideIndicator.init()),
  { once: true }
);
window.addEventListener("unload", () => HostOverrideIndicator.uninit(), {
  once: true,
});
