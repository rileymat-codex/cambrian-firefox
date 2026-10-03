/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_net_HostOverride_h
#define mozilla_net_HostOverride_h

#include "mozilla/Maybe.h"
#include "nsString.h"
#include "nsTArray.h"

namespace mozilla::net {

struct HostOverride {
  nsCString mAddress;
  bool mInsecure = false;
};

Maybe<HostOverride> LookupHostOverride(const nsACString& aHost);
bool HasHostOverrides();

}  // namespace mozilla::net

#endif
