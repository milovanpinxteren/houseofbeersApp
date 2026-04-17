import { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Platform,
  Animated,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { colors, spacing, borderRadius } from '../theme/colors';
import { t } from '../i18n';

const IOS_INSTALL_DISMISSED_KEY = 'ios_install_prompt_dismissed';

/**
 * Detects if we're running on iOS web (not standalone PWA mode)
 * Works for all iOS browsers (Safari, Chrome, Firefox, etc.)
 */
function isIOSWeb(): boolean {
  if (Platform.OS !== 'web') return false;

  const ua = navigator.userAgent;
  const isIOS = /iPad|iPhone|iPod/.test(ua) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const isStandalone = (window.navigator as any).standalone === true;

  return isIOS && !isStandalone;
}

export default function IOSInstallPrompt() {
  const [visible, setVisible] = useState(false);
  const [fadeAnim] = useState(new Animated.Value(0));

  useEffect(() => {
    checkShouldShow();
  }, []);

  const checkShouldShow = async () => {
    if (!isIOSWeb()) return;

    try {
      const dismissed = await AsyncStorage.getItem(IOS_INSTALL_DISMISSED_KEY);
      if (!dismissed) {
        setVisible(true);
        Animated.timing(fadeAnim, {
          toValue: 1,
          duration: 300,
          useNativeDriver: true,
        }).start();
      }
    } catch (error) {
      console.error('Error checking install prompt state:', error);
    }
  };

  const handleDismiss = async () => {
    try {
      await AsyncStorage.setItem(IOS_INSTALL_DISMISSED_KEY, 'true');
      Animated.timing(fadeAnim, {
        toValue: 0,
        duration: 200,
        useNativeDriver: true,
      }).start(() => setVisible(false));
    } catch (error) {
      console.error('Error dismissing install prompt:', error);
      setVisible(false);
    }
  };

  if (!visible) return null;

  return (
    <Animated.View style={[styles.container, { opacity: fadeAnim }]}>
      <View style={styles.content}>
        <TouchableOpacity
          style={styles.closeButton}
          onPress={handleDismiss}
          hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
        >
          <Ionicons name="close" size={20} color={colors.textMuted} />
        </TouchableOpacity>

        <View style={styles.iconRow}>
          <View style={styles.appIcon}>
            <Text style={styles.appIconText}>HoB</Text>
          </View>
        </View>

        <Text style={styles.title}>{t('install.title')}</Text>
        <Text style={styles.description}>{t('install.description')}</Text>

        <View style={styles.instructions}>
          <View style={styles.step}>
            <View style={styles.stepNumber}>
              <Text style={styles.stepNumberText}>1</Text>
            </View>
            <Text style={styles.stepText}>
              {t('install.step1')} <Ionicons name="share-outline" size={16} color={colors.primary} />
            </Text>
          </View>

          <View style={styles.step}>
            <View style={styles.stepNumber}>
              <Text style={styles.stepNumberText}>2</Text>
            </View>
            <Text style={styles.stepText}>
              {t('install.step2')} <Ionicons name="add-square-outline" size={16} color={colors.primary} />
            </Text>
          </View>
        </View>
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.primary + '40',
    overflow: 'hidden',
  },
  content: {
    padding: spacing.md,
    position: 'relative',
  },
  closeButton: {
    position: 'absolute',
    top: spacing.sm,
    right: spacing.sm,
    zIndex: 1,
  },
  iconRow: {
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  appIcon: {
    width: 50,
    height: 50,
    borderRadius: 12,
    backgroundColor: colors.background,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.primary,
  },
  appIconText: {
    color: colors.primary,
    fontWeight: '700',
    fontSize: 14,
  },
  title: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text,
    textAlign: 'center',
    marginBottom: spacing.xs,
  },
  description: {
    fontSize: 14,
    color: colors.textMuted,
    textAlign: 'center',
    marginBottom: spacing.md,
  },
  instructions: {
    gap: spacing.sm,
  },
  step: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  stepNumber: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: spacing.sm,
  },
  stepNumberText: {
    color: colors.background,
    fontWeight: '600',
    fontSize: 12,
  },
  stepText: {
    fontSize: 14,
    color: colors.text,
    flex: 1,
  },
});
