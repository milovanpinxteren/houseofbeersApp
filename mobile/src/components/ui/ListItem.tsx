import { ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors, spacing } from '../../theme/colors';
import { Badge } from './Badge';

type IconName = keyof typeof Ionicons.glyphMap;

interface ListItemProps {
  icon?: IconName;
  iconColor?: string;
  label: string;
  subtitle?: string;
  badge?: number | string;
  right?: ReactNode;
  chevron?: boolean;
  onPress?: () => void;
  last?: boolean;
}

/** Row for menu/settings lists. Use inside a Card with padded={false}. */
export function ListItem({
  icon, iconColor = colors.primary, label, subtitle,
  badge, right, chevron = true, onPress, last,
}: ListItemProps) {
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      style={({ pressed }) => [
        styles.row,
        !last && styles.divider,
        pressed && onPress && { backgroundColor: colors.surfaceHigh },
      ]}
    >
      {icon && (
        <View style={styles.iconWrap}>
          <Ionicons name={icon} size={20} color={iconColor} />
        </View>
      )}
      <View style={styles.content}>
        <Text style={styles.label}>{label}</Text>
        {subtitle ? <Text style={styles.subtitle} numberOfLines={1}>{subtitle}</Text> : null}
      </View>
      {badge !== undefined && <Badge value={badge} />}
      {right}
      {chevron && onPress && (
        <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 14,
    paddingHorizontal: spacing.md,
    gap: spacing.md,
  },
  divider: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  iconWrap: {
    width: 38,
    height: 38,
    borderRadius: 12,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  content: {
    flex: 1,
  },
  label: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text,
  },
  subtitle: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 2,
  },
});
