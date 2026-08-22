import { Redirect, useLocalSearchParams } from 'expo-router';

// Push notifications link to /raffle/{id}; the real screen lives inside the
// (profile) sub-stack so the tab bar stays visible (same pattern as the old
// /favorites redirect).
export default function RaffleRedirect() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return <Redirect href={`/(tabs)/(profile)/raffle/${id}` as any} />;
}
