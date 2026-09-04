"""Puntentool: staff-only admin pages to award or correct a member's points.

Mounted at /admin/points-tool/ (single include in config/urls.py, before
admin/ so the admin catch-all cannot shadow it). Same pattern as the Campagne
Studio: `staff_member_required` on every view, Dutch-first UI, templates
rendered inside the admin chrome and styled with the Studio's own
admin-theme-aware stylesheet.

The money-moving part lives in `loyalty.services.points_tool`; these views
only parse the form, render the confirmation step and report the result.

The member search reuses the Studio's `user_search` endpoint verbatim (see
points_tool_urls) rather than growing a second copy of the same query.
"""
import logging

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, redirect, render

from loyalty.services import points_tool as tool
from loyalty.services.grants import grant_notification_text
from loyalty.services.points_value import (
    format_euro, points_to_euro, rate_info,
)

logger = logging.getLogger(__name__)

MODES = ('add', 'set')


def _int_or_none(raw):
    # Spaces only: a "1.500" is rejected rather than silently read as 15 or
    # 1500 — guessing at a thousands separator on a money field is how digits
    # get lost.
    raw = (raw or '').strip().replace(' ', '')
    if raw == '':
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_form(post):
    """
    Builder POST -> (values dict, NL error list).

    The euro input is a helper only: the JS mirrors it into the points field,
    which is what the server reads. A euro number that never became points is
    therefore never awarded — better than two fields quietly disagreeing.
    """
    errors = []

    mode = post.get('mode') or 'add'
    if mode not in MODES:
        mode = 'add'

    reason = (post.get('reason') or '').strip()
    points_raw = (post.get('points') or '').strip()
    target_raw = (post.get('target_balance') or '').strip()
    points = _int_or_none(points_raw)
    target = _int_or_none(target_raw)

    if not reason:
        errors.append(
            'Vul een reden in — die ziet het lid in de app.' if mode == 'add'
            else 'Vul een reden in voor de correctie (voor het logboek).'
        )
    elif len(reason) > 255:
        errors.append('De reden is te lang (maximaal 255 tekens).')

    if mode == 'add':
        if points is None:
            errors.append('Vul een aantal punten in.')
        elif points < 1:
            errors.append('Het aantal punten moet minstens 1 zijn.')
        elif points > tool.MAX_POINTS:
            errors.append(f'Maximaal {tool.MAX_POINTS} punten per keer.')
    else:
        if target is None:
            errors.append('Vul het nieuwe saldo in.')
        elif target < 0:
            errors.append(
                'Een saldo kan niet negatief zijn — vul 0 of hoger in.'
            )
        elif target > tool.MAX_POINTS:
            errors.append(
                f'Een saldo van meer dan {tool.MAX_POINTS} punten kan niet.'
            )

    values = {
        'mode': mode,
        'reason': reason,
        'points': points_raw,
        'target_balance': target_raw,
        'euro': (post.get('euro') or '').strip(),
        'notify': bool(post.get('notify')),
        'token': (post.get('token') or '').strip(),
    }
    return values, points, target, errors


def _member_context(member, form, errors=None):
    snapshot = tool.member_snapshot(member)
    rate = rate_info()
    return {
        'title': f'Punten — {member.email}',
        'member': member,
        'snapshot': snapshot,
        'rate': rate,
        'rate_per_point': format_euro(rate['rate']),
        'rate_value': str(rate['rate']),
        'form': form,
        'errors': errors or [],
        'max_points': tool.MAX_POINTS,
        'warn_points': tool.WARN_POINTS,
    }


def _blank_form():
    return {
        'mode': 'add', 'reason': '', 'points': '', 'target_balance': '',
        'euro': '', 'notify': True, 'token': '',
    }


@staff_member_required
def index(request):
    """Landing page: find a member, plus the tool's own recent actions."""
    rate = rate_info()
    return render(request, 'loyalty/points_tool/index.html', {
        'title': 'Puntentool',
        'rate': rate,
        'rate_per_point': format_euro(rate['rate']),
        'recent': tool.recent_actions(),
    })


@staff_member_required
def member(request, user_id):
    """
    Member page: balance card + award form (GET), validation and the
    confirmation step (POST step=confirm), execution (POST step=execute).

    Confirming is a separate request on purpose: this moves real money
    (1 punt = ~€0,05) and a single mis-click should not be able to do it.
    """
    from users.models import User

    member_obj = get_object_or_404(User, pk=user_id)

    if request.method != 'POST':
        return render(
            request, 'loyalty/points_tool/member.html',
            _member_context(member_obj, _blank_form()),
        )

    form, points, target, errors = _parse_form(request.POST)
    step = request.POST.get('step') or 'confirm'

    if errors:
        return render(
            request, 'loyalty/points_tool/member.html',
            _member_context(member_obj, form, errors),
        )

    if step == 'execute':
        return _execute(request, member_obj, form, points, target)

    return _confirm(request, member_obj, form, points, target)


def _confirm(request, member_obj, form, points, target):
    """Render the "weet je het zeker" screen with the resulting balance."""
    snapshot = tool.member_snapshot(member_obj)
    current = snapshot['balance']

    if form['mode'] == 'add':
        delta = points
        new_balance = current + points
        title, body = grant_notification_text(points, form['reason'])
    else:
        delta = target - current
        new_balance = target
        title, body = tool.correction_notification_text(target, form['reason'])
        if delta == 0:
            return render(
                request, 'loyalty/points_tool/member.html',
                _member_context(member_obj, form, [
                    f'Het saldo is al {target} punten — er is niets te wijzigen.'
                ]),
            )

    # Minted here, posted back with the confirmation: a resubmitted
    # confirmation reuses the same dedupe key and awards nothing extra.
    form = dict(form, token=form['token'] or tool.new_action_token())

    context = _member_context(member_obj, form)
    context.update({
        'title': f'Bevestigen — {member_obj.email}',
        'delta': delta,
        'delta_euro': format_euro(points_to_euro(abs(delta))),
        'new_balance': new_balance,
        'new_balance_euro': format_euro(points_to_euro(new_balance)),
        'warnings': tool.award_warnings(delta),
        'notification_title': title,
        'notification_body': body,
    })
    return render(request, 'loyalty/points_tool/confirm.html', context)


def _execute(request, member_obj, form, points, target):
    try:
        if form['mode'] == 'add':
            result = tool.add_points(
                member=member_obj,
                points=points,
                reason=form['reason'],
                staff_user=request.user,
                notify=form['notify'],
                token=form['token'] or None,
            )
            if not result['created']:
                messages.warning(
                    request,
                    'Deze toekenning was al verwerkt — er zijn geen extra '
                    'punten toegekend.',
                )
            else:
                extra = ' Het lid heeft een melding gekregen.' if result['notified'] else ''
                messages.success(
                    request,
                    f'{result["points"]} punten toegekend aan '
                    f'{member_obj.email}. Nieuw saldo: {result["balance"]}.{extra}',
                )
        else:
            result = tool.set_balance(
                member=member_obj,
                target=target,
                reason=form['reason'],
                staff_user=request.user,
                notify=form['notify'],
            )
            messages.success(
                request,
                f'Saldo van {member_obj.email} staat nu op {result["balance"]} '
                f'punten ({result["delta"]:+d}).',
            )
    except tool.PointsToolError as e:
        return render(
            request, 'loyalty/points_tool/member.html',
            _member_context(member_obj, form, [str(e)]),
        )
    except Exception as e:  # pragma: no cover - unexpected failure
        logger.error(
            f"Points tool failed for {member_obj.email}: {e}", exc_info=True
        )
        return render(
            request, 'loyalty/points_tool/member.html',
            _member_context(member_obj, form, [
                'Er ging iets mis bij het verwerken. Probeer het opnieuw.'
            ]),
        )

    return redirect('points_tool:member', user_id=member_obj.pk)
