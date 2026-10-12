"""
Celery tasks for the events app. Only the prize-payment sweep lives here —
draws, fulfillment and auction control are deliberately request-synchronous
on the regie page (staff want the result in their face, and the volumes
are tiny).
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def check_prize_payments():
    """Nightly: ask Shopify whether open prize/auction draft orders were
    paid (see services/payments.py). Best effort — a Shopify hiccup skips
    that row and the next night catches it."""
    from .services.payments import sweep_payments

    summary = sweep_payments()
    logger.info(f'Prize payment sweep: {summary}')
    return summary
