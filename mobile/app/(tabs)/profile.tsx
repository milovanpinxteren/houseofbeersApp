import { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Platform,
  Modal,
  FlatList,
  TextInput,
  Alert,
  ActivityIndicator,
  TouchableOpacity,
  Pressable,
} from 'react-native';
import { router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '../../src/context/AuthContext';
import { useLanguage } from '../../src/context/LanguageContext';
import { syncShopify, updateProfile } from '../../src/api/auth';
import { t } from '../../src/i18n';
import { colors, spacing, borderRadius, fonts, type } from '../../src/theme/colors';
import { Screen, Card, Button, ListItem, SectionHeader, useToast } from '../../src/components/ui';
import BirthdaySettings from '../../src/components/BirthdaySettings';
import NotificationSettings from '../../src/components/NotificationSettings';

export default function ProfileScreen() {
  const { user, logout, refreshUser } = useAuth();
  const { language, setLanguage, languages } = useLanguage();
  const { showToast } = useToast();
  const [showConfirm, setShowConfirm] = useState(false);
  const [showLanguagePicker, setShowLanguagePicker] = useState(false);
  const [showEditProfile, setShowEditProfile] = useState(false);
  const [editFirstName, setEditFirstName] = useState('');
  const [editLastName, setEditLastName] = useState('');
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  function handleRefresh() {
    setIsRefreshing(true);
    Promise.resolve(refreshUser?.()).finally(() => setIsRefreshing(false));
  }

  async function handleLogout() {
    if (Platform.OS === 'web') {
      setShowConfirm(true);
    } else {
      await doLogout();
    }
  }

  async function doLogout() {
    setIsLoggingOut(true);
    try {
      await logout();
      router.replace('/(auth)/login');
    } catch (error) {
      console.log('[Profile] Logout error:', error);
    } finally {
      setIsLoggingOut(false);
      setShowConfirm(false);
    }
  }

  async function handleSyncShopify() {
    if (isSyncing) return;
    setIsSyncing(true);
    try {
      await syncShopify();
      if (refreshUser) {
        await refreshUser();
      }
      showToast(t('profile.syncSuccess'), 'success');
    } catch (error) {
      console.log('[Profile] Sync error:', error);
      showToast(t('profile.syncError'), 'error');
    } finally {
      setIsSyncing(false);
    }
  }

  async function handleLanguageSelect(code: string) {
    await setLanguage(code);
    setShowLanguagePicker(false);
  }

  function openEditProfile() {
    setEditFirstName(user?.first_name || '');
    setEditLastName(user?.last_name || '');
    setShowEditProfile(true);
  }

  async function handleSaveProfile() {
    setIsSavingProfile(true);
    try {
      await updateProfile({
        first_name: editFirstName.trim(),
        last_name: editLastName.trim(),
      });
      await refreshUser();
      setShowEditProfile(false);
    } catch (error) {
      console.log('[Profile] Save error:', error);
      Alert.alert(t('common.error'), t('profile.saveError'));
    } finally {
      setIsSavingProfile(false);
    }
  }

  const currentLanguage = languages.find((l) => l.code === language);

  const displayName =
    user?.first_name || user?.last_name
      ? `${user?.first_name || ''} ${user?.last_name || ''}`.trim()
      : t('profile.guest');

  const initials = (() => {
    const first = user?.first_name?.trim()?.[0] || '';
    const last = user?.last_name?.trim()?.[0] || '';
    if (first || last) return `${first}${last}`.toUpperCase();
    return (user?.email?.[0] || '?').toUpperCase();
  })();

  return (
    <Screen refreshing={isRefreshing} onRefresh={handleRefresh}>
      {/* Identity */}
      <Card style={styles.identityCard} onPress={openEditProfile}>
        <View style={styles.identityRow}>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>{initials}</Text>
          </View>
          <View style={styles.identityInfo}>
            <Text style={styles.userName} numberOfLines={1}>
              {displayName}
            </Text>
            <Text style={styles.userEmail} numberOfLines={1}>
              {user?.email}
            </Text>
          </View>
          <View style={styles.editIcon}>
            <Ionicons name="pencil" size={15} color={colors.textMuted} />
          </View>
        </View>
      </Card>

      {/* Account */}
      <SectionHeader title={t('profile.account')} />
      <Card padded={false}>
        <ListItem
          icon="receipt-outline"
          label={t('profile.orders')}
          subtitle={
            user?.shopify_customer_id
              ? t('profile.viewOrderHistory')
              : t('profile.linkShopifyFirst')
          }
          onPress={() => router.push('/(profile)/orders' as any)}
        />
        <ListItem
          icon="beer-outline"
          label={t('profile.connectUntappd')}
          subtitle={t('profile.connectUntappdHint')}
          onPress={() => router.push('/(profile)/connect-untappd' as any)}
        />
        <ListItem
          icon="sync-outline"
          label={t('profile.syncShopify')}
          subtitle={
            user?.shopify_customer_id
              ? t('profile.shopifyLinked')
              : t('profile.shopifyNotLinked')
          }
          chevron={false}
          right={
            isSyncing ? (
              <ActivityIndicator size="small" color={colors.primary} />
            ) : undefined
          }
          onPress={handleSyncShopify}
          last
        />
      </Card>

      {/* Preferences */}
      <SectionHeader title={t('profile.preferences')} />
      <Card padded={false}>
        <BirthdaySettings />
        <NotificationSettings />
        <ListItem
          icon="language-outline"
          label={t('profile.language')}
          subtitle={currentLanguage?.nativeName}
          onPress={() => setShowLanguagePicker(true)}
          last
        />
      </Card>

      {/* Logout */}
      {showConfirm ? (
        <Card variant="elevated" style={styles.confirmCard}>
          <Text style={styles.confirmText}>{t('profile.logoutConfirm')}</Text>
          <View style={styles.confirmButtons}>
            <Button
              label={t('cancel')}
              variant="ghost"
              onPress={() => setShowConfirm(false)}
              style={styles.confirmButton}
            />
            <Button
              label={t('profile.logout')}
              variant="danger"
              loading={isLoggingOut}
              onPress={doLogout}
              style={styles.confirmButton}
            />
          </View>
        </Card>
      ) : (
        <Button
          label={t('profile.logout')}
          variant="danger"
          icon="log-out-outline"
          loading={isLoggingOut}
          onPress={handleLogout}
          style={styles.logoutButton}
        />
      )}

      {/* Edit Profile Modal */}
      <Modal
        visible={showEditProfile}
        transparent
        animationType="fade"
        onRequestClose={() => setShowEditProfile(false)}
      >
        <View style={styles.modalOverlay}>
          <TouchableOpacity
            style={StyleSheet.absoluteFill}
            activeOpacity={1}
            onPress={() => setShowEditProfile(false)}
          />
          <View style={styles.editModalContent}>
            <Text style={styles.modalTitle}>{t('profile.editProfile')}</Text>
            <View style={styles.inputGroup}>
              <Text style={styles.inputLabel}>{t('auth.firstName')}</Text>
              <TextInput
                style={styles.textInput}
                value={editFirstName}
                onChangeText={setEditFirstName}
                placeholder={t('auth.firstName')}
                placeholderTextColor={colors.textMuted}
                autoCapitalize="words"
              />
            </View>
            <View style={styles.inputGroup}>
              <Text style={styles.inputLabel}>{t('auth.lastName')}</Text>
              <TextInput
                style={styles.textInput}
                value={editLastName}
                onChangeText={setEditLastName}
                placeholder={t('auth.lastName')}
                placeholderTextColor={colors.textMuted}
                autoCapitalize="words"
              />
            </View>
            <View style={styles.modalButtons}>
              <Button
                label={t('common.cancel')}
                variant="ghost"
                onPress={() => setShowEditProfile(false)}
                style={styles.modalButton}
              />
              <Button
                label={t('save')}
                loading={isSavingProfile}
                onPress={handleSaveProfile}
                style={styles.modalButton}
              />
            </View>
          </View>
        </View>
      </Modal>

      {/* Language Picker Modal */}
      <Modal
        visible={showLanguagePicker}
        transparent
        animationType="fade"
        onRequestClose={() => setShowLanguagePicker(false)}
      >
        <TouchableOpacity
          style={styles.modalOverlay}
          activeOpacity={1}
          onPress={() => setShowLanguagePicker(false)}
        >
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>{t('profile.selectLanguage')}</Text>
            <FlatList
              data={languages}
              keyExtractor={(item) => item.code}
              renderItem={({ item }) => (
                <Pressable
                  style={({ pressed }) => [
                    styles.languageOption,
                    item.code === language && styles.languageOptionSelected,
                    pressed && { opacity: 0.85 },
                  ]}
                  onPress={() => handleLanguageSelect(item.code)}
                >
                  <Text
                    style={[
                      styles.languageOptionText,
                      item.code === language && styles.languageOptionTextSelected,
                    ]}
                  >
                    {item.nativeName}
                  </Text>
                  {item.code === language && (
                    <Ionicons name="checkmark" size={20} color={colors.primary} />
                  )}
                </Pressable>
              )}
            />
          </View>
        </TouchableOpacity>
      </Modal>
    </Screen>
  );
}

const styles = StyleSheet.create({
  // Identity
  identityCard: {
    marginTop: spacing.md,
  },
  identityRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  avatar: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.primary + '1A',
    justifyContent: 'center',
    alignItems: 'center',
  },
  avatarText: {
    fontFamily: fonts.heading,
    fontSize: 22,
    letterSpacing: 1,
    color: colors.primary,
  },
  identityInfo: {
    flex: 1,
  },
  userName: {
    ...type.title,
  },
  userEmail: {
    fontSize: 13,
    color: colors.textMuted,
    marginTop: 2,
  },
  editIcon: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.surfaceHigh,
    justifyContent: 'center',
    alignItems: 'center',
  },

  // Logout
  logoutButton: {
    marginTop: spacing.xl,
  },
  confirmCard: {
    marginTop: spacing.xl,
  },
  confirmText: {
    ...type.serifBody,
    textAlign: 'center',
    marginBottom: spacing.md,
  },
  confirmButtons: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  confirmButton: {
    flex: 1,
  },

  // Modals
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.72)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    backgroundColor: colors.surfaceHigh,
    borderRadius: borderRadius.lg,
    padding: spacing.lg,
    width: '80%',
    maxWidth: 300,
  },
  editModalContent: {
    backgroundColor: colors.surfaceHigh,
    borderRadius: borderRadius.lg,
    padding: spacing.lg,
    width: '85%',
    maxWidth: 340,
  },
  modalTitle: {
    ...type.heading,
    fontSize: 18,
    textAlign: 'center',
    marginBottom: spacing.md,
  },
  inputGroup: {
    marginBottom: spacing.md,
  },
  inputLabel: {
    ...type.label,
    fontSize: 12,
    marginBottom: spacing.xs,
  },
  textInput: {
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    fontSize: 16,
    color: colors.text,
  },
  modalButtons: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  modalButton: {
    flex: 1,
  },

  // Language options
  languageOption: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: spacing.md,
    borderRadius: borderRadius.md,
    minHeight: 48,
  },
  languageOptionSelected: {
    backgroundColor: colors.primary + '18',
  },
  languageOptionText: {
    fontSize: 16,
    color: colors.text,
  },
  languageOptionTextSelected: {
    color: colors.primary,
    fontWeight: '600',
  },
});
