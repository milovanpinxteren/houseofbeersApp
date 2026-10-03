import { useCallback, useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  Image,
  StyleSheet,
  Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { t } from '../i18n';
import { colors, spacing, borderRadius, fonts } from '../theme/colors';
import { useToast } from './ui';
import { ApiError } from '../api/client';
import { AuctionItem, placeBid } from '../api/events';

type Props = {
  item: AuctionItem;
  eventId: number;
  isLive: boolean;
};

/**
 * Compact auction panel between the video and the chat. Shows the item
 * being auctioned (so late joiners know what the bidding is about) and,
 * while active, an integer-only bid input — bids go through their own
 * endpoint, never through chat.
 */
export default function AuctionPanel({ item, eventId, isLive }: Props) {
  const { showToast } = useToast();
  const [bidText, setBidText] = useState('');
  const [placing, setPlacing] = useState(false);
  // Authoritative top bid from our own accepted bid; the 3s poll lags a
  // beat behind, so without this the member's own bid looks ignored.
  const [localTop, setLocalTop] = useState<{ amount: number; name: string } | null>(null);
  // Highest amount WE successfully bid on this item; leading is derived
  // (effective bid === ours — nobody else can match it, increments force
  // strictly higher bids), so it survives the poll catching up.
  const [myTopBid, setMyTopBid] = useState<number | null>(null);
  const placingRef = useRef(false);

  // Drop the local override once the poll has caught up, and reset all
  // bid state when a different item becomes active.
  useEffect(() => {
    if (localTop && (item.current_bid ?? 0) >= localTop.amount) {
      setLocalTop(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.current_bid]);
  const itemIdRef = useRef(item.id);
  useEffect(() => {
    if (itemIdRef.current !== item.id) {
      itemIdRef.current = item.id;
      setLocalTop(null);
      setMyTopBid(null);
      setBidText('');
    }
  }, [item.id]);

  const polledBid = item.current_bid ?? 0;
  const localWins = localTop !== null && localTop.amount > polledBid;
  const effectiveBid = localWins ? localTop!.amount : (item.current_bid ?? null);
  const effectiveLeader = localWins ? localTop!.name : item.leader_name;
  const iAmLeading = myTopBid !== null && effectiveBid === myTopBid;
  const startPrice = Math.ceil(parseFloat(item.starting_price) || 0);
  const minNext = effectiveBid != null
    ? effectiveBid + (item.min_increment || 1)
    : startPrice;

  const submitBid = useCallback(
    async (amount: number) => {
      if (placingRef.current) return;
      placingRef.current = true;
      setPlacing(true);
      try {
        const res = await placeBid(eventId, amount);
        setLocalTop({ amount: res.current_bid, name: res.leader_name });
        setBidText('');
        if (res.current_bid === amount) {
          setMyTopBid(amount);
        } else {
          // A racing bid beat ours between request and response.
          showToast(
            t('events.auctionOutbid', { amount: res.current_bid }),
            'error'
          );
        }
      } catch (err) {
        console.error('Bid error:', err);
        if (err instanceof ApiError && err.status === 429) {
          showToast(t('events.auctionThrottled'), 'error');
        } else if (err instanceof ApiError && err.status === 400) {
          const body = (err.body ?? {}) as { error?: string; minimum?: number };
          if (body.error === 'too_low') {
            showToast(
              t('events.auctionBidTooLow', { minimum: body.minimum ?? minNext }),
              'error'
            );
          } else if (body.error === 'not_live' || body.error === 'no_active_item') {
            showToast(t('events.auctionClosed'), 'error');
          } else {
            showToast(t('events.auctionBidError'), 'error');
          }
        } else {
          showToast(t('events.auctionBidError'), 'error');
        }
      } finally {
        placingRef.current = false;
        setPlacing(false);
      }
    },
    [eventId, minNext, showToast]
  );

  const handleCustomBid = useCallback(() => {
    const amount = parseInt(bidText, 10);
    if (!amount || Number.isNaN(amount)) return;
    submitBid(amount);
  }, [bidText, submitBid]);

  const metaParts = [
    item.brewery,
    item.size,
    item.untappd_rating ? `★ ${parseFloat(item.untappd_rating).toFixed(2)}` : null,
  ].filter(Boolean);

  const bidCountLabel =
    item.bid_count === 1
      ? t('events.auctionBidCountOne')
      : t('events.auctionBidCount', { count: item.bid_count });

  return (
    <View style={styles.panel}>
      <View style={styles.headerRow}>
        <Ionicons name="hammer" size={14} color={colors.primary} />
        <Text style={styles.label}>{t('events.auction')}</Text>
        {item.status === 'active' && isLive && (
          <View style={styles.liveDotWrap}>
            <View style={styles.liveDot} />
          </View>
        )}
      </View>

      <View style={styles.bodyRow}>
        {!!item.image_url && (
          <Image source={{ uri: item.image_url }} style={styles.image} />
        )}
        <View style={styles.info}>
          <Text style={styles.title} numberOfLines={2}>{item.title}</Text>
          {metaParts.length > 0 && (
            <Text style={styles.meta}>{metaParts.join(' • ')}</Text>
          )}

          {item.status === 'sold' ? (
            <Text style={styles.soldLine}>
              {t('events.soldFor')} €{Math.round(parseFloat(item.final_price || '0'))}
              {item.winner_name ? ` ${t('events.soldTo')} ${item.winner_name}` : ''}
            </Text>
          ) : effectiveBid != null ? (
            <Text style={styles.bidLine}>
              {t('events.auctionHighestBid')}:{' '}
              <Text style={styles.bidAmount}>€{effectiveBid}</Text>
              {effectiveLeader ? ` — ${effectiveLeader}` : ''}
              {item.bid_count > 0 ? `  (${bidCountLabel})` : ''}
            </Text>
          ) : (
            <Text style={styles.bidLine}>
              {t('events.auctionNoBids')} — {t('events.startingAt').toLowerCase()} €{startPrice}
            </Text>
          )}

          {iAmLeading && item.status === 'active' && (
            <Text style={styles.leadingLine}>{t('events.auctionYouLead')}</Text>
          )}
        </View>
      </View>

      {item.status === 'active' && isLive && (
        <View style={styles.bidRow}>
          <TouchableOpacity
            style={[styles.quickBidButton, placing && styles.bidDisabled]}
            onPress={() => submitBid(minNext)}
            disabled={placing}
            activeOpacity={0.85}
          >
            <Text style={styles.quickBidText}>
              {t('events.auctionQuickBid', { amount: minNext })}
            </Text>
          </TouchableOpacity>
          <TextInput
            style={styles.bidInput}
            value={bidText}
            onChangeText={(v) => setBidText(v.replace(/[^0-9]/g, ''))}
            placeholder={t('events.auctionBidPlaceholder')}
            placeholderTextColor={colors.textMuted}
            keyboardType="number-pad"
            inputMode="numeric"
            maxLength={5}
            onSubmitEditing={handleCustomBid}
            returnKeyType="send"
          />
          <TouchableOpacity
            style={[
              styles.bidSendButton,
              (!bidText || placing) && styles.bidDisabled,
            ]}
            onPress={handleCustomBid}
            disabled={!bidText || placing}
          >
            <Ionicons
              name="arrow-up"
              size={18}
              color={bidText && !placing ? colors.background : colors.textMuted}
            />
          </TouchableOpacity>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    borderLeftWidth: 3,
    borderLeftColor: colors.primary,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 4,
  },
  label: {
    fontFamily: fonts.heading,
    color: colors.primary,
    fontSize: 11,
    letterSpacing: 1.5,
    textTransform: 'uppercase',
  },
  liveDotWrap: {
    marginLeft: 2,
  },
  liveDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.live,
  },
  bodyRow: {
    flexDirection: 'row',
    gap: spacing.sm + 2,
  },
  image: {
    width: 54,
    height: 54,
    borderRadius: borderRadius.md,
    backgroundColor: colors.surfaceHigh,
  },
  info: {
    flex: 1,
  },
  title: {
    fontFamily: fonts.heading,
    color: colors.text,
    fontSize: 16,
    letterSpacing: 0.4,
  },
  meta: {
    color: colors.textMuted,
    fontSize: 12,
    marginTop: 1,
  },
  bidLine: {
    color: colors.textMuted,
    fontSize: 13,
    marginTop: 3,
  },
  bidAmount: {
    fontFamily: fonts.headingBold,
    color: colors.text,
    fontSize: 14,
  },
  soldLine: {
    fontFamily: fonts.heading,
    color: colors.success,
    fontSize: 13,
    letterSpacing: 0.3,
    marginTop: 3,
  },
  leadingLine: {
    fontFamily: fonts.heading,
    color: colors.warning,
    fontSize: 12,
    letterSpacing: 0.5,
    marginTop: 3,
    textTransform: 'uppercase',
  },
  bidRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  quickBidButton: {
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    borderRadius: borderRadius.pill,
  },
  quickBidText: {
    fontFamily: fonts.headingBold,
    color: colors.background,
    fontSize: 13,
    letterSpacing: 0.6,
  },
  bidInput: {
    flex: 1,
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: Platform.OS === 'ios' ? 8 : 6,
    color: colors.text,
    fontSize: 14,
  },
  bidSendButton: {
    backgroundColor: colors.primary,
    width: 34,
    height: 34,
    borderRadius: 17,
    justifyContent: 'center',
    alignItems: 'center',
  },
  bidDisabled: {
    backgroundColor: colors.surfaceHigh,
  },
});
