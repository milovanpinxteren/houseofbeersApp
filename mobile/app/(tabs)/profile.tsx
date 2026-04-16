import { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  StyleSheet,
  Platform,
  Modal,
  FlatList,
  RefreshControl,
  TextInput,
  Alert,
} from 'react-native';
import { router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '../../src/context/AuthContext';
import { useLanguage } from '../../src/context/LanguageContext';
import { syncShopify, updateProfile } from '../../src/api/auth';
import { t } from '../../src/i18n';
import { colors, spacing, borderRadius } from '../../src/theme/colors';
import {
  getUntappdProfile,
  getFavorites,
  UntappdProfile,
} from '../../src/api/recommendations';

type IconName = React.ComponentProps<typeof Ionicons>['name'];

interface MenuItem {
  id: string;
  icon: IconName;
  label: string;
  subtitle?: string;
  route: string;
  badge?: number;
  showChevron?: boolean;
}

export default function ProfileScreen() {
  const { user, logout, refreshUser } = useAuth();
  const { language, setLanguage, languages } = useLanguage();
  const [showConfirm, setShowConfirm] = useState(false);
  const [showLanguagePicker, setShowLanguagePicker] = useState(false);
  const [showEditProfile, setShowEditProfile] = useState(false);
  const [editFirstName, setEditFirstName] = useState('');
  const [editLastName, setEditLastName] = useState('');
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [untappdProfile, setUntappdProfile] = useState<UntappdProfile | null>(null);
  const [favoritesCount, setFavoritesCount] = useState(0);

  const loadProfileData = useCallback(async () => {
    try {
      const [untappdData, favoritesData] = await Promise.all([
        getUntappdProfile(),
        getFavorites(),
      ]);
      setUntappdProfile(untappdData.untappd);
      setFavoritesCount(favoritesData.favorites.length);
    } catch (err) {
      console.log('[Profile] Load data error:', err);
    }
  }, []);

  useEffect(() => {
    loadProfileData();
  }, [loadProfileData]);

  function handleRefresh() {
    setIsRefreshing(true);
    loadProfileData().finally(() => setIsRefreshing(false));
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
    setIsSyncing(true);
    try {
      await syncShopify();
      if (refreshUser) {
        await refreshUser();
      }
    } catch (error) {
      console.log('[Profile] Sync error:', error);
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

  const menuItems: MenuItem[] = [
    {
      id: 'recommendations',
      icon: 'beer',
      label: t('profile.recommendations'),
      subtitle: untappdProfile
        ? t('profile.connectedAs', { username: untappdProfile.username })
        : t('profile.basedOnOrders'),
      route: '/(profile)/recommendations',
      showChevron: true,
    },
    {
      id: 'taste-profile',
      icon: 'analytics',
      label: t('profile.tasteProfile'),
      subtitle: t('profile.tasteProfileSubtitle'),
      route: '/(profile)/taste-profile',
      showChevron: true,
    },
    {
      id: 'favorites',
      icon: 'heart',
      label: t('profile.favorites'),
      subtitle: t('profile.favoritesSubtitle'),
      route: '/(profile)/favorites',
      badge: favoritesCount > 0 ? favoritesCount : undefined,
      showChevron: true,
    },
    {
      id: 'orders',
      icon: 'receipt',
      label: t('profile.orders'),
      subtitle: user?.shopify_customer_id
        ? t('profile.viewOrderHistory')
        : t('profile.linkShopifyFirst'),
      route: '/(profile)/orders',
      showChevron: true,
    },
  ];

  function renderMenuItem(item: MenuItem) {
    return (
      <TouchableOpacity
        key={item.id}
        style={styles.menuItem}
        onPress={() => router.push(item.route as any)}
        activeOpacity={0.7}
      >
        <View style={styles.menuIconContainer}>
          <Ionicons name={item.icon} size={22} color={colors.primary} />
        </View>
        <View style={styles.menuContent}>
          <Text style={styles.menuLabel}>{item.label}</Text>
          {item.subtitle && (
            <Text style={styles.menuSubtitle} numberOfLines={1}>
              {item.subtitle}
            </Text>
          )}
        </View>
        {item.badge && (
          <View style={styles.badge}>
            <Text style={styles.badgeText}>{item.badge}</Text>
          </View>
        )}
        {item.showChevron && (
          <Ionicons name="chevron-forward" size={20} color={colors.textMuted} />
        )}
      </TouchableOpacity>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      refreshControl={
        <RefreshControl
          refreshing={isRefreshing}
          onRefresh={handleRefresh}
          tintColor={colors.primary}
        />
      }
    >
      {/* User Info Card */}
      <TouchableOpacity
        style={styles.userCard}
        onPress={openEditProfile}
        activeOpacity={0.7}
      >
        <View style={styles.avatarContainer}>
          <Ionicons name="person-circle" size={60} color={colors.primary} />
        </View>
        <View style={styles.userInfo}>
          <Text style={styles.userName}>
            {user?.first_name || user?.last_name
              ? `${user?.first_name || ''} ${user?.last_name || ''}`.trim()
              : t('profile.guest')}
          </Text>
          <Text style={styles.userEmail}>{user?.email}</Text>
          <Text style={styles.editHint}>{t('profile.tapToEdit')}</Text>
        </View>
        <Ionicons name="pencil" size={18} color={colors.textMuted} />
      </TouchableOpacity>

      {/* Untappd Connection Card */}
      <TouchableOpacity
        style={styles.untappdCard}
        onPress={() => router.push('/(profile)/connect-untappd')}
        activeOpacity={0.7}
      >
        <View style={styles.untappdLeft}>
          <Ionicons
            name={untappdProfile ? 'checkmark-circle' : 'link'}
            size={24}
            color={untappdProfile ? colors.success : colors.primary}
          />
          <View style={styles.untappdInfo}>
            <Text style={styles.untappdTitle}>
              {untappdProfile ? 'Untappd' : t('profile.connectUntappd')}
            </Text>
            <Text style={styles.untappdSubtitle}>
              {untappdProfile
                ? `@${untappdProfile.username}`
                : t('profile.connectUntappdHint')}
            </Text>
          </View>
        </View>
        <Ionicons name="chevron-forward" size={20} color={colors.textMuted} />
      </TouchableOpacity>

      {/* Menu Section */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>{t('profile.yourBeerJourney')}</Text>
        <View style={styles.menuCard}>
          {menuItems.map((item) => renderMenuItem(item))}
        </View>
      </View>

      {/* Settings Section */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>{t('profile.settings')}</Text>
        <View style={styles.menuCard}>
          {/* Shopify Sync */}
          <TouchableOpacity
            style={styles.menuItem}
            onPress={handleSyncShopify}
            disabled={isSyncing}
            activeOpacity={0.7}
          >
            <View style={styles.menuIconContainer}>
              <Ionicons name="sync" size={22} color={colors.primary} />
            </View>
            <View style={styles.menuContent}>
              <Text style={styles.menuLabel}>{t('profile.syncShopify')}</Text>
              <Text style={styles.menuSubtitle}>
                {user?.shopify_customer_id
                  ? t('profile.shopifyLinked')
                  : t('profile.shopifyNotLinked')}
              </Text>
            </View>
            {isSyncing && (
              <Text style={styles.syncingText}>{t('profile.syncing')}</Text>
            )}
          </TouchableOpacity>

          {/* Language */}
          <TouchableOpacity
            style={styles.menuItem}
            onPress={() => setShowLanguagePicker(true)}
            activeOpacity={0.7}
          >
            <View style={styles.menuIconContainer}>
              <Ionicons name="language" size={22} color={colors.primary} />
            </View>
            <View style={styles.menuContent}>
              <Text style={styles.menuLabel}>{t('profile.language')}</Text>
              <Text style={styles.menuSubtitle}>{currentLanguage?.nativeName}</Text>
            </View>
            <Ionicons name="chevron-forward" size={20} color={colors.textMuted} />
          </TouchableOpacity>
        </View>
      </View>

      {/* Logout */}
      {showConfirm ? (
        <View style={styles.confirmBox}>
          <Text style={styles.confirmText}>{t('profile.logoutConfirm')}</Text>
          <View style={styles.confirmButtons}>
            <TouchableOpacity
              style={styles.cancelButton}
              onPress={() => setShowConfirm(false)}
            >
              <Text style={styles.cancelText}>{t('cancel')}</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.logoutButtonInline, isLoggingOut && styles.buttonDisabled]}
              onPress={doLogout}
              disabled={isLoggingOut}
            >
              <Text style={styles.logoutText}>
                {isLoggingOut ? t('profile.loggingOut') : t('profile.logout')}
              </Text>
            </TouchableOpacity>
          </View>
        </View>
      ) : (
        <TouchableOpacity style={styles.logoutButton} onPress={handleLogout}>
          <Ionicons name="log-out-outline" size={20} color={colors.text} />
          <Text style={styles.logoutText}>{t('profile.logout')}</Text>
        </TouchableOpacity>
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
            <View style={styles.editModalButtons}>
              <TouchableOpacity
                style={styles.editCancelButton}
                onPress={() => setShowEditProfile(false)}
              >
                <Text style={styles.editCancelText}>{t('common.cancel')}</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.editSaveButton, isSavingProfile && styles.buttonDisabled]}
                onPress={handleSaveProfile}
                disabled={isSavingProfile}
              >
                <Text style={styles.editSaveText}>
                  {isSavingProfile ? t('loading') : t('save')}
                </Text>
              </TouchableOpacity>
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
                <TouchableOpacity
                  style={[
                    styles.languageOption,
                    item.code === language && styles.languageOptionSelected,
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
                </TouchableOpacity>
              )}
            />
          </View>
        </TouchableOpacity>
      </Modal>

      <View style={styles.bottomPadding} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },

  // User Card
  userCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    margin: spacing.md,
    padding: spacing.md,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.primary + '40',
  },
  avatarContainer: {
    marginRight: spacing.md,
  },
  userInfo: {
    flex: 1,
  },
  userName: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.text,
  },
  userEmail: {
    fontSize: 14,
    color: colors.textMuted,
    marginTop: 2,
  },
  editHint: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 4,
    fontStyle: 'italic',
  },

  // Untappd Card
  untappdCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.surface,
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  untappdLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  untappdInfo: {
    marginLeft: spacing.md,
    flex: 1,
  },
  untappdTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text,
  },
  untappdSubtitle: {
    fontSize: 13,
    color: colors.textMuted,
    marginTop: 2,
  },

  // Sections
  section: {
    marginBottom: spacing.md,
  },
  sectionTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textMuted,
    textTransform: 'uppercase',
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  menuCard: {
    backgroundColor: colors.surface,
    marginHorizontal: spacing.md,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
    overflow: 'hidden',
  },

  // Menu Items
  menuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.tertiary + '20',
  },
  menuIconContainer: {
    width: 36,
    height: 36,
    borderRadius: 8,
    backgroundColor: colors.primary + '15',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: spacing.md,
  },
  menuContent: {
    flex: 1,
  },
  menuLabel: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text,
  },
  menuSubtitle: {
    fontSize: 13,
    color: colors.textMuted,
    marginTop: 2,
  },
  badge: {
    backgroundColor: colors.primary,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
    marginRight: spacing.sm,
  },
  badgeText: {
    color: colors.background,
    fontSize: 12,
    fontWeight: '600',
  },
  syncingText: {
    fontSize: 13,
    color: colors.primary,
    marginRight: spacing.sm,
  },

  // Logout
  logoutButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.secondary,
    marginHorizontal: spacing.md,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    gap: spacing.sm,
  },
  logoutButtonInline: {
    flex: 1,
    backgroundColor: colors.secondary,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    alignItems: 'center',
  },
  logoutText: {
    color: colors.text,
    fontSize: 16,
    fontWeight: '600',
  },
  buttonDisabled: {
    opacity: 0.6,
  },

  // Confirm Box
  confirmBox: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.lg,
    marginHorizontal: spacing.md,
    borderWidth: 1,
    borderColor: colors.secondary,
  },
  confirmText: {
    color: colors.text,
    fontSize: 16,
    textAlign: 'center',
    marginBottom: spacing.md,
  },
  confirmButtons: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  cancelButton: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.textMuted,
  },
  cancelText: {
    color: colors.textMuted,
    fontSize: 16,
    fontWeight: '600',
  },

  // Modal
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.lg,
    width: '80%',
    maxWidth: 300,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.md,
    textAlign: 'center',
  },
  languageOption: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: spacing.md,
    borderRadius: borderRadius.md,
  },
  languageOptionSelected: {
    backgroundColor: colors.primary + '20',
  },
  languageOptionText: {
    fontSize: 16,
    color: colors.text,
  },
  languageOptionTextSelected: {
    color: colors.primary,
    fontWeight: '600',
  },

  // Edit Profile Modal
  editModalContent: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.lg,
    width: '85%',
    maxWidth: 340,
  },
  inputGroup: {
    marginBottom: spacing.md,
  },
  inputLabel: {
    fontSize: 14,
    color: colors.textMuted,
    marginBottom: spacing.xs,
  },
  textInput: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    fontSize: 16,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  editModalButtons: {
    flexDirection: 'row',
    gap: spacing.md,
    marginTop: spacing.sm,
  },
  editCancelButton: {
    flex: 1,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.textMuted,
  },
  editCancelText: {
    color: colors.textMuted,
    fontSize: 16,
    fontWeight: '600',
  },
  editSaveButton: {
    flex: 1,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    alignItems: 'center',
    backgroundColor: colors.primary,
  },
  editSaveText: {
    color: colors.background,
    fontSize: 16,
    fontWeight: '600',
  },

  bottomPadding: {
    height: spacing.xl,
  },
});
