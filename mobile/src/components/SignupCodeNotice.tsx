import { useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { useToast } from './ui/Toast';
import { t } from '../i18n';
import {
  clearStoredSignupCode,
  ensureSignupCodeCaptured,
  getStoredSignupCode,
} from '../utils/signupCode';

/**
 * A welcome code that reached someone who is already a member.
 *
 * Two ways in, one answer: they opened a flyer link while logged in, or they
 * had a code stored and then logged in instead of registering. Either way the
 * bonus is for new accounts only, so we say so once and drop the code —
 * silently swallowing it leaves them waiting for points that will never come,
 * and keeping it means nagging on every launch.
 */
export function SignupCodeNotice() {
  const { isAuthenticated } = useAuth();
  const handled = useRef(false);
  const { showToast } = useToast();

  useEffect(() => {
    if (!isAuthenticated || handled.current) return;

    (async () => {
      // Must await the capture: the toast would otherwise race the moment the
      // launch URL is written to storage.
      await ensureSignupCodeCaptured();
      const code = await getStoredSignupCode();
      if (!code || handled.current) return;

      handled.current = true;
      await clearStoredSignupCode();
      showToast(t('auth.signupCodeAlreadyMember'), 'info');
    })();
  }, [isAuthenticated, showToast]);

  return null;
}
