import { Redirect } from 'expo-router';

// Links (push, QR) use /pickup; the pickup RSVP UI lives on the orders screen
// inside the (profile) sub-stack so the tab bar stays visible (same pattern
// as the /raffle/[id] redirect). The `pickup` param auto-expands the section.
export default function PickupRedirect() {
  return <Redirect href={'/(tabs)/(profile)/orders?pickup=1' as any} />;
}
