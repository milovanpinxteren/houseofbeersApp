import { Redirect } from 'expo-router';

// Favorites moved into the Ontdek section; keep old links/bookmarks working.
export default function FavoritesRedirect() {
  return <Redirect href="/(tabs)/(profile)/favorites" />;
}
