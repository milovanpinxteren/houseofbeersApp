import { Stack, router } from 'expo-router';
import { Image, StyleSheet, TouchableOpacity } from 'react-native';
import { colors } from '../../../src/theme/colors';

function LogoTitle() {
  return (
    <TouchableOpacity onPress={() => router.replace('/(tabs)')} activeOpacity={0.7}>
      <Image
        source={require('../../../assets/logo.png')}
        style={styles.logo}
        resizeMode="contain"
      />
    </TouchableOpacity>
  );
}

export default function ProfileStackLayout() {
  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: colors.background },
        headerTintColor: colors.text,
        headerTitle: () => <LogoTitle />,
        headerTitleAlign: 'center',
        headerBackTitle: '',
      }}
    />
  );
}

const styles = StyleSheet.create({
  logo: {
    height: 44,
    width: 180,
  },
});
