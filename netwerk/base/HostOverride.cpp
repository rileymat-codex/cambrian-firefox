/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "HostOverride.h"

#include <cstring>

#include "mozilla/StaticPrefs_network.h"
#include "nsCharSeparatedTokenizer.h"
#include "nsNetAddr.h"
#include "nsReadableUtils.h"
#include "nsURLHelper.h"

namespace mozilla::net {

namespace {

struct ParsedOverrides {
  nsTArray<HostOverride> mEntries;
  nsTArray<nsCString> mHosts;
};

bool ParseIPv4(nsACString& aValue, NetAddr& aAddress) {
  uint32_t octets = 0;
  uint32_t value = 0;
  uint32_t digits = 0;
  bool leadingZero = false;
  bool haveDigit = false;
  for (uint32_t i = 0; i < aValue.Length(); ++i) {
    char c = aValue.CharAt(i);
    if (c >= '0' && c <= '9') {
      haveDigit = true;
      if (digits == 0) {
        leadingZero = c == '0';
      } else if (leadingZero) {
        return false;
      }
      if (++digits > 3) {
        return false;
      }
      value = value * 10 + (c - '0');
      if (value > 255) {
        return false;
      }
    } else if (c == '.' && haveDigit) {
      ++octets;
      value = 0;
      haveDigit = false;
      digits = 0;
      leadingZero = false;
    } else {
      return false;
    }
  }
  if (!haveDigit || octets != 3 || NS_FAILED(aAddress.InitFromString(aValue)) ||
      aAddress.raw.family != AF_INET) {
    return false;
  }
  return true;
}

bool Parse(ParsedOverrides& aResult) {
  const auto pref = StaticPrefs::network_host_overrides();
  nsAutoCString input(*pref);
  input.Trim(" \t\r\n");
  if (input.IsEmpty()) {
    return true;
  }
  if (input.Last() == ',') {
    return false;
  }
  nsCCharSeparatedTokenizer tokenizer(input, ',');
  for (const nsACString& raw : tokenizer.ToRange()) {
    nsAutoCString entry(raw);
    entry.Trim(" \t\r\n");
    if (entry.IsEmpty()) {
      return false;
    }

    int32_t equals = entry.FindChar('=');
    if (equals <= 0 || equals == int32_t(entry.Length() - 1) ||
        entry.FindChar('=', equals + 1) >= 0) {
      return false;
    }

    nsAutoCString host(Substring(entry, 0, equals));
    nsAutoCString value(Substring(entry, equals + 1));
    host.Trim(" \t\r\n");
    value.Trim(" \t\r\n");

    bool insecure = false;
    if (StringEndsWith(value, "|insecure"_ns)) {
      insecure = true;
      value.Truncate(value.Length() - strlen("|insecure"));
      value.Trim(" \t\r\n");
    }

    if (host.IsEmpty() || value.IsEmpty() || !net_IsValidDNSHost(host)) {
      return false;
    }
    for (uint32_t i = 0; i < host.Length(); ++i) {
      char c = host.CharAt(i);
      if (static_cast<unsigned char>(c) >= 0x80 || c == ':' || c == '*') {
        return false;
      }
    }
    if (host.Last() == '.') {
      host.Truncate(host.Length() - 1);
    }
    if (host.IsEmpty()) {
      return false;
    }
    ToLowerCase(host);

    NetAddr addr;
    if (!ParseIPv4(value, addr)) {
      return false;
    }
    NetAddr hostAddress;
    if (NS_SUCCEEDED(hostAddress.InitFromString(host))) {
      return false;
    }

    if (aResult.mHosts.Contains(host)) {
      return false;
    }
    aResult.mHosts.AppendElement(host);
    nsAutoCString canonicalAddress;
    addr.ToString(canonicalAddress);
    aResult.mEntries.AppendElement(
        HostOverride{std::move(canonicalAddress), insecure});
  }
  return true;
}

}  // namespace

Maybe<HostOverride> LookupHostOverride(const nsACString& aHost) {
  nsAutoCString host(aHost);
  if (host.IsEmpty()) {
    return Nothing();
  }
  if (host.Last() == '.') {
    host.Truncate(host.Length() - 1);
  }
  ToLowerCase(host);

  ParsedOverrides parsed;
  if (!Parse(parsed)) {
    return Nothing();
  }
  for (uint32_t i = 0; i < parsed.mHosts.Length(); ++i) {
    if (parsed.mHosts[i].Equals(host)) {
      return Some(parsed.mEntries[i]);
    }
  }
  return Nothing();
}

bool HasHostOverrides() {
  ParsedOverrides parsed;
  return Parse(parsed) && !parsed.mEntries.IsEmpty();
}

}  // namespace mozilla::net
