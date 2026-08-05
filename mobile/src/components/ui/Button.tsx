import { ActivityIndicator, Platform, Pressable, StyleSheet, Text, ViewStyle, StyleProp } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { colors, spacing, borderRadius, fonts } from '../../theme/colors';

type IconName = keyof typeof Ionicons.glyphMap;

interface ButtonProps {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'md' | 'sm';
  icon?: IconName;
  disabled?: boolean;
  loading?: boolean;
  style?: StyleProp<ViewStyle>;
}

export function Button({
  label, onPress, variant = 'primary', size = 'md',
  icon, disabled, loading, style,
}: ButtonProps) {
  const isPrimary = variant === 'primary';
  const isDanger = variant === 'danger';
  const contentColor =
    isPrimary ? colors.background
    : isDanger ? colors.error
    : colors.primary;

  function handlePress() {
    if (Platform.OS !== 'web') {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    }
    onPress();
  }

  return (
    <Pressable
      onPress={handlePress}
      disabled={disabled || loading}
      style={({ pressed }) => [
        styles.base,
        size === 'sm' ? styles.sm : styles.md,
        variant === 'primary' && styles.primary,
        variant === 'secondary' && styles.secondary,
        variant === 'ghost' && styles.ghost,
        variant === 'danger' && styles.danger,
        (disabled || loading) && styles.disabled,
        pressed && !disabled && { opacity: 0.85, transform: [{ scale: 0.98 }] },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator size="small" color={contentColor} />
      ) : (
        <>
          {icon && <Ionicons name={icon} size={size === 'sm' ? 14 : 17} color={contentColor} />}
          <Text
            style={[
              styles.label,
              size === 'sm' && styles.labelSm,
              { color: contentColor },
            ]}
          >
            {label}
          </Text>
        </>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    borderRadius: borderRadius.md,
  },
  md: {
    paddingVertical: 12,
    paddingHorizontal: spacing.lg,
  },
  sm: {
    paddingVertical: 7,
    paddingHorizontal: spacing.md,
  },
  primary: {
    backgroundColor: colors.primary,
  },
  secondary: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  ghost: {
    backgroundColor: 'transparent',
  },
  danger: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: colors.error + '55',
  },
  disabled: {
    opacity: 0.5,
  },
  label: {
    fontFamily: fonts.heading,
    fontSize: 15,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
  },
  labelSm: {
    fontSize: 12,
    letterSpacing: 0.6,
  },
});
