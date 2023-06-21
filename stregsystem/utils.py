import logging
import re
import smtplib

from django.utils.dateparse import parse_datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.test.runner import DiscoverRunner

from django.db.models import Count, F, Q, QuerySet
from django.utils import timezone
from stregsystem.templatetags.stregsystem_extras import money

import qrcode
import qrcode.image.svg

logger = logging.getLogger(__name__)


def make_active_productlist_query(queryset) -> QuerySet:
    now = timezone.now()
    # Create a query for the set of products that MIGHT be active. Might
    # because they can be out of stock. Which we compute later
    active_candidates = queryset.filter(Q(active=True) & (Q(deactivate_date=None) | Q(deactivate_date__gte=now)))
    # This query selects all the candidates that are out of stock.
    candidates_out_of_stock = (
        active_candidates.filter(sale__timestamp__gt=F("start_date"))
        .annotate(c=Count("sale__id"))
        .filter(c__gte=F("quantity"))
        .values("id")
    )
    # We can now create a query that selects all the candidates which are not
    # out of stock.
    return active_candidates.exclude(Q(start_date__isnull=False) & Q(id__in=candidates_out_of_stock))


def make_inactive_productlist_query(queryset) -> QuerySet:
    now = timezone.now()
    # Create a query of things are definitively inactive. Some of the ones
    # filtered here might be out of stock, but we include that later.
    inactive_candidates = queryset.exclude(
        Q(active=True) & (Q(deactivate_date=None) | Q(deactivate_date__gte=now))
    ).values("id")
    inactive_out_of_stock = (
        queryset.filter(sale__timestamp__gt=F("start_date"))
        .annotate(c=Count("sale__id"))
        .filter(c__gte=F("quantity"))
        .values("id")
    )
    return queryset.filter(Q(id__in=inactive_candidates) | Q(id__in=inactive_out_of_stock))


def make_room_specific_query(room) -> QuerySet:
    return Q(rooms__id=room) | Q(rooms=None)


def make_unprocessed_mobilepayment_query() -> QuerySet:
    from stregsystem.models import MobilePayment  # import locally to avoid circular import

    return MobilePayment.objects.filter(Q(payment__isnull=True) & Q(status__exact=MobilePayment.UNSET)).order_by(
        '-timestamp'
    )


def make_processed_mobilepayment_query() -> QuerySet:
    from stregsystem.models import MobilePayment  # import locally to avoid circular import

    return MobilePayment.objects.filter(
        Q(payment__isnull=True)
        & Q(member__isnull=False)
        & Q(status__in=[MobilePayment.APPROVED, MobilePayment.IGNORED])
    )


def make_unprocessed_member_filled_mobilepayment_query() -> QuerySet:
    from stregsystem.models import MobilePayment  # import locally to avoid circular import

    return MobilePayment.objects.filter(
        Q(payment__isnull=True) & Q(status=MobilePayment.UNSET) & Q(amount__gte=5000) & Q(member__isnull=False)
    )


def date_to_midnight(date):
    """
    Converts a datetime.date to a datetime of the same date at midnight.

    :param date: date to convert
    :return: the date as a timezone aware datetime at midnight
    """
    return timezone.make_aware(timezone.datetime(date.year, date.month, date.day, 0, 0))


def send_payment_mail(member, amount, mobilepay_comment):
    if hasattr(settings, 'TEST_MODE'):
        return
    msg = MIMEMultipart()
    msg['From'] = 'treo@fklub.dk'
    msg['To'] = member.email
    msg['Subject'] = 'Stregsystem payment'

    formatted_amount = money(amount)

    from django.utils.html import escape
    from django.template.loader import render_to_string

    context = dict()
    context.update(vars(member))
    context.update({'formatted_balance': money(member.balance)})
    # TODO: not sure if escape serves any purpose here, since it's already being passed through a template.
    context.update({'mobilepay_comment': escape(mobilepay_comment)})

    target_template = "deposit_manual.html" if mobilepay_comment else "deposit_automatic.html"
    html = render_to_string(f"templates/mail/{target_template}", context)

    msg.attach(MIMEText(html, 'html'))

    try:
        smtpObj = smtplib.SMTP('localhost', 25)
        smtpObj.sendmail('treo@fklub.dk', member.email, msg.as_string())
    except Exception as e:
        logger.error(str(e))


def parse_csv_and_create_mobile_payments(csv_file):
    imported_transactions, duplicate_transactions = 0, 0
    import csv

    # get csv reader and ignore header
    reader = csv.reader(csv_file[1:], delimiter=';', quotechar='"')
    for row in reader:
        from stregsystem.models import MobilePayment

        mobile_payment = MobilePayment(
            member=None,
            amount=row[2].replace(',', ''),
            timestamp=parse_datetime(row[3]),
            customer_name=row[4],
            transaction_id=row[7],
            comment=row[6],
            payment=None,
        )
        try:
            # unique constraint on transaction_id and payment-foreign key must hold before saving new object
            mobile_payment.validate_unique()

            # do case insensitive exact match on active members
            mobile_payment.member = mobile_payment_exact_match_member(mobile_payment.comment)
            mobile_payment.save()
            imported_transactions += 1
        except ValidationError:
            duplicate_transactions += 1
    return imported_transactions, duplicate_transactions


def mobile_payment_exact_match_member(comment):
    from stregsystem.models import Member

    match = Member.objects.filter(username__iexact=comment.strip(), active=True)
    if match.count() == 1:
        return match.get()
    elif match.count() > 1:
        # something is very wrong, there should be no active users which are duplicates post PR #178
        raise RuntimeError("Duplicate usernames found at MobilePayment import. Should not exist post PR #178")


def strip_emoji(text):
    # allowlist decided by string.printables and all unique chars from usernames
    return re.sub(
        '[^a-zA-Z0-9äåæéëöø!"#$%&()*+,\-_./:;<=>?@\\\^`\]{|}~£§¶Ø\s]',
        '',
        text,
    ).strip()


def qr_code(data):
    response = HttpResponse(content_type="image/svg+xml")
    qr = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathFillImage)
    qr.save(response)

    return response


class stregsystemTestRunner(DiscoverRunner):
    def __init__(self, *args, **kwargs):
        settings.TEST_MODE = True
        super(stregsystemTestRunner, self).__init__(*args, **kwargs)


class MobilePaytoolException(RuntimeError):
    """
    Structured exception for runtime error due to race condition during submission of MobilePaytool form
    """

    def __init__(self, racy_mbpayments: QuerySet):
        self.racy_mbpayments = racy_mbpayments
        self.inconsistent_mbpayments_count = self.racy_mbpayments.count()
        self.inconsistent_transaction_ids = [x.transaction_id for x in self.racy_mbpayments]
