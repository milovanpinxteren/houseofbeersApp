import { useState, useRef, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  GestureResponderEvent,
  LayoutChangeEvent,
  Platform,
} from 'react-native';
import { colors, spacing } from '../theme/colors';

interface PriceSliderProps {
  min: number;
  max: number;
  value: number;
  onChange: (value: number) => void;
  onChangeEnd?: (value: number) => void;
  step?: number;
}

export default function PriceSlider({
  min,
  max,
  value,
  onChange,
  onChangeEnd,
  step = 1,
}: PriceSliderProps) {
  const sliderWidthRef = useRef(0);
  const trackRef = useRef<View>(null);
  const [isDragging, setIsDragging] = useState(false);

  // Calculate percentage for display
  const percentage = Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));

  const handleLayout = useCallback((event: LayoutChangeEvent) => {
    sliderWidthRef.current = event.nativeEvent.layout.width;
  }, []);

  const handleTouch = useCallback((event: GestureResponderEvent) => {
    const width = sliderWidthRef.current;
    if (width === 0) return;

    const locationX = event.nativeEvent.locationX;
    const clampedX = Math.max(0, Math.min(locationX, width));
    const rawValue = min + (clampedX / width) * (max - min);
    const steppedValue = Math.round(rawValue / step) * step;
    const finalValue = Math.max(min, Math.min(max, steppedValue));

    onChange(finalValue);
    return finalValue;
  }, [min, max, step, onChange]);

  const handleTouchStart = useCallback((event: GestureResponderEvent) => {
    setIsDragging(true);
    handleTouch(event);
  }, [handleTouch]);

  const handleTouchMove = useCallback((event: GestureResponderEvent) => {
    handleTouch(event);
  }, [handleTouch]);

  const handleTouchEnd = useCallback((event: GestureResponderEvent) => {
    setIsDragging(false);
    const width = sliderWidthRef.current;
    if (width === 0) return;

    const locationX = event.nativeEvent.locationX;
    const clampedX = Math.max(0, Math.min(locationX, width));
    const rawValue = min + (clampedX / width) * (max - min);
    const steppedValue = Math.round(rawValue / step) * step;
    const finalValue = Math.max(min, Math.min(max, steppedValue));

    onChange(finalValue);
    if (onChangeEnd) {
      onChangeEnd(finalValue);
    }
  }, [min, max, step, onChange, onChangeEnd]);

  return (
    <View style={styles.container}>
      <View
        ref={trackRef}
        style={styles.track}
        onLayout={handleLayout}
        onStartShouldSetResponder={() => true}
        onMoveShouldSetResponder={() => true}
        onResponderGrant={handleTouchStart}
        onResponderMove={handleTouchMove}
        onResponderRelease={handleTouchEnd}
      >
        <View style={[styles.fill, { width: `${percentage}%` }]} />
        <View
          style={[
            styles.thumb,
            {
              left: `${percentage}%`,
              transform: [{ translateX: -12 }],
            },
            isDragging && styles.thumbActive,
          ]}
        />
      </View>
      <View style={styles.labels}>
        <Text style={styles.label}>€{min}</Text>
        <Text style={styles.label}>€{max}+</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    width: '100%',
  },
  track: {
    height: 32,
    backgroundColor: colors.tertiary + '40',
    borderRadius: 16,
    justifyContent: 'center',
    ...(Platform.OS === 'web' ? { cursor: 'pointer' } : {}),
  } as any,
  fill: {
    position: 'absolute',
    left: 0,
    height: '100%',
    backgroundColor: colors.primary,
    borderRadius: 16,
  },
  thumb: {
    position: 'absolute',
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: colors.text,
    borderWidth: 3,
    borderColor: colors.primary,
    top: 2,
    ...(Platform.OS === 'web' ? { cursor: 'grab' } : {}),
  } as any,
  thumbActive: {
    transform: [{ translateX: -12 }, { scale: 1.1 }],
    ...(Platform.OS === 'web' ? { cursor: 'grabbing' } : {}),
  } as any,
  labels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: spacing.xs,
    paddingHorizontal: 4,
  },
  label: {
    fontSize: 12,
    color: colors.textMuted,
  },
});
