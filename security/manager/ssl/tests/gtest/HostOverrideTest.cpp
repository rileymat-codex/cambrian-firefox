/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this file,
 * You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "NSSSocketControl.h"
#include "SSLServerCertVerification.h"
#include "gtest/gtest.h"
#include "mozilla/Preferences.h"
#include "nsNSSIOLayer.h"
#include "nsReadableUtils.h"

using mozilla::MakeRefPtr;
using mozilla::Preferences;
using mozilla::psm::MatchesInsecureHostOverride;

TEST(HostOverride, PeerIdSnapshotSeparatesModeAndAddress)
{
  Preferences::SetCString("network.host_overrides", "");
  RefPtr<nsSSLIOLayerHelpers> helpers =
      MakeRefPtr<nsSSLIOLayerHelpers>(PublicOrPrivate::Public, 0);
  RefPtr<NSSSocketControl> ordinary = MakeRefPtr<NSSSocketControl>(
      "example.com"_ns, 443, helpers.forget(), 0, 0);
  Preferences::SetCString("network.host_overrides",
                          "example.com=127.0.0.2|insecure");
  nsAutoCString ordinaryPeerId;
  ASSERT_EQ(NS_OK, ordinary->GetPeerId(ordinaryPeerId));
  EXPECT_EQ(ordinaryPeerId.Find("hostoverride:"), kNotFound);
  EXPECT_FALSE(ordinary->GetHostOverride());

  Preferences::SetCString("network.host_overrides", "example.com=127.0.0.2");
  RefPtr<nsSSLIOLayerHelpers> normalHelpers =
      MakeRefPtr<nsSSLIOLayerHelpers>(PublicOrPrivate::Public, 0);
  RefPtr<NSSSocketControl> normal = MakeRefPtr<NSSSocketControl>(
      "example.com"_ns, 443, normalHelpers.forget(), 0, 0);
  Preferences::SetCString("network.host_overrides",
                          "example.com=127.0.0.2|insecure");
  nsAutoCString normalPeerId;
  ASSERT_EQ(NS_OK, normal->GetPeerId(normalPeerId));
  EXPECT_NE(normalPeerId.Find("hostoverride:normal:127.0.0.2:"), kNotFound);
  const auto& snapshot = normal->GetHostOverride();
  ASSERT_TRUE(snapshot);
  EXPECT_FALSE(MatchesInsecureHostOverride("example.com"_ns, "127.0.0.2"_ns,
                                           snapshot->mAddress,
                                           snapshot->mInsecure));

  RefPtr<nsSSLIOLayerHelpers> insecureHelpers =
      MakeRefPtr<nsSSLIOLayerHelpers>(PublicOrPrivate::Public, 0);
  RefPtr<NSSSocketControl> insecure = MakeRefPtr<NSSSocketControl>(
      "example.com"_ns, 443, insecureHelpers.forget(), 0, 0);
  nsAutoCString insecurePeerId;
  ASSERT_EQ(NS_OK, insecure->GetPeerId(insecurePeerId));
  EXPECT_NE(insecurePeerId.Find("hostoverride:insecure:127.0.0.2:"), kNotFound);
  EXPECT_NE(normalPeerId, insecurePeerId);

  Preferences::SetCString("network.host_overrides", "example.com=127.0.0.3");
  nsAutoCString stablePeerId;
  ASSERT_EQ(NS_OK, insecure->GetPeerId(stablePeerId));
  EXPECT_EQ(insecurePeerId, stablePeerId);

  RefPtr<nsSSLIOLayerHelpers> addressHelpers =
      MakeRefPtr<nsSSLIOLayerHelpers>(PublicOrPrivate::Public, 0);
  RefPtr<NSSSocketControl> addressChanged = MakeRefPtr<NSSSocketControl>(
      "example.com"_ns, 443, addressHelpers.forget(), 0, 0);
  nsAutoCString addressChangedPeerId;
  ASSERT_EQ(NS_OK, addressChanged->GetPeerId(addressChangedPeerId));
  EXPECT_NE(addressChangedPeerId, normalPeerId);

  RefPtr<nsSSLIOLayerHelpers> otherHelpers =
      MakeRefPtr<nsSSLIOLayerHelpers>(PublicOrPrivate::Public, 0);
  RefPtr<NSSSocketControl> other = MakeRefPtr<NSSSocketControl>(
      "example.com"_ns, 443, otherHelpers.forget(), 0, 0);
  mozilla::OriginAttributes attrs;
  attrs.mPrivateBrowsingId = 1;
  other->SetOriginAttributes(attrs);
  nsAutoCString privatePeerId;
  ASSERT_EQ(NS_OK, other->GetPeerId(privatePeerId));
  nsAutoCString suffix;
  attrs.CreateSuffix(suffix);
  EXPECT_TRUE(StringEndsWith(privatePeerId, suffix));

  nsAutoCString otherPeerId;
  ASSERT_EQ(NS_OK, other->GetPeerId(otherPeerId));
  EXPECT_NE(otherPeerId.Find("hostoverride:normal:127.0.0.3:"), kNotFound);

  RefPtr<nsSSLIOLayerHelpers> unrelatedHelpers =
      MakeRefPtr<nsSSLIOLayerHelpers>(PublicOrPrivate::Public, 0);
  RefPtr<NSSSocketControl> unrelated = MakeRefPtr<NSSSocketControl>(
      "other.example.com"_ns, 443, unrelatedHelpers.forget(), 0, 0);
  nsAutoCString unrelatedPeerId;
  ASSERT_EQ(NS_OK, unrelated->GetPeerId(unrelatedPeerId));
  EXPECT_EQ(unrelatedPeerId.Find("hostoverride:"), kNotFound);
  Preferences::SetCString("network.host_overrides", "");
}

TEST(HostOverride, InsecureContextPredicate)
{
  Preferences::SetCString("network.host_overrides",
                          "example.com=127.0.0.2|insecure");
  EXPECT_TRUE(MatchesInsecureHostOverride("example.com"_ns, "127.0.0.2"_ns,
                                          "127.0.0.2"_ns, true));
  EXPECT_FALSE(MatchesInsecureHostOverride("example.com"_ns, "127.0.0.3"_ns,
                                           "127.0.0.2"_ns, true));
  EXPECT_FALSE(MatchesInsecureHostOverride("example.com"_ns, "127.0.0.2"_ns,
                                           "127.0.0.3"_ns, true));
  EXPECT_FALSE(MatchesInsecureHostOverride("example.com"_ns, "127.0.0.2"_ns,
                                           "127.0.0.2"_ns, false));
  EXPECT_FALSE(MatchesInsecureHostOverride("example.com"_ns, ""_ns,
                                           "127.0.0.2"_ns, true));
  EXPECT_FALSE(MatchesInsecureHostOverride(
      "other.example.com"_ns, "127.0.0.2"_ns, "127.0.0.2"_ns, true));

  EXPECT_FALSE(MatchesInsecureHostOverride("example.com"_ns, "127.0.0.2"_ns,
                                           ""_ns, true));
  Preferences::SetCString("network.host_overrides",
                          "example.com=127.0.0.3|insecure");
  EXPECT_FALSE(MatchesInsecureHostOverride("example.com"_ns, "127.0.0.2"_ns,
                                           "127.0.0.2"_ns, true));
  Preferences::SetCString("network.host_overrides", "example.com=127.0.0.2");
  EXPECT_FALSE(MatchesInsecureHostOverride("example.com"_ns, "127.0.0.2"_ns,
                                           "127.0.0.2"_ns, true));
  Preferences::SetCString("network.host_overrides", "");
  EXPECT_FALSE(MatchesInsecureHostOverride("example.com"_ns, "127.0.0.2"_ns,
                                           "127.0.0.2"_ns, true));
}
