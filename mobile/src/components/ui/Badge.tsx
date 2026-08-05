import { StyleSheet, Text, View } from 'react-native';
import { colors, borderRadius } from '../../theme/colors';

interface BadgeProps {
  value: number | string;
  color?: string;
}

export function Badge({ value, color = colors.primary }: BadgeProps) {
  return (
    <View style={[styles.badge, { backgroundColor: color }]}>
      <Text style={styles.text}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    minWidth: 20,
    height: 20,
    borderRadius: borderRadius.pill,
    paddingHorizontal: 6,
    justifyContent: 'center',
    alignItems: 'center',
  },
  text: {
    color: colors.background,
    fontSize: 11,
    fontWeight: '700',
  },
});
