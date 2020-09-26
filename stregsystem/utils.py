import logging
import smtplib
import datetime
from backports.datetime_fromisoformat import MonkeyPatch
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from django.conf import settings
from django.core.exceptions import ValidationError
from django.test.runner import DiscoverRunner

from django.db.models import Count, F, Q
from django.utils import timezone
from stregsystem.templatetags.stregsystem_extras import money

logger = logging.getLogger(__name__)
MonkeyPatch.patch_fromisoformat()  # FIXME: remove when updated to py37 or newer


def make_active_productlist_query(queryset):
    now = timezone.now()
    # Create a query for the set of products that MIGHT be active. Might
    # because they can be out of stock. Which we compute later
    active_candidates = (
        queryset
            .filter(
            Q(active=True)
            & (Q(deactivate_date=None) | Q(deactivate_date__gte=now)))
    )
    # This query selects all the candidates that are out of stock.
    candidates_out_of_stock = (
        active_candidates
            .filter(sale__timestamp__gt=F("start_date"))
            .annotate(c=Count("sale__id"))
            .filter(c__gte=F("quantity"))
            .values("id")
    )
    # We can now create a query that selects all the candidates which are not
    # out of stock.
    return (
        active_candidates
            .exclude(
            Q(start_date__isnull=False)
            & Q(id__in=candidates_out_of_stock)))


def make_inactive_productlist_query(queryset):
    now = timezone.now()
    # Create a query of things are definitively inactive. Some of the ones
    # filtered here might be out of stock, but we include that later.
    inactive_candidates = (
        queryset
            .exclude(
            Q(active=True)
            & (Q(deactivate_date=None) | Q(deactivate_date__gte=now)))
            .values("id")
    )
    inactive_out_of_stock = (
        queryset
            .filter(sale__timestamp__gt=F("start_date"))
            .annotate(c=Count("sale__id"))
            .filter(c__gte=F("quantity"))
            .values("id")
    )
    return (
        queryset
            .filter(
            Q(id__in=inactive_candidates)
            | Q(id__in=inactive_out_of_stock))
    )


def make_room_specific_query(room):
    return (
            Q(rooms__id=room) | Q(rooms=None)
    )


def make_unprocessed_mobilepayment_query():
    from stregsystem.models import MobilePayment  # import locally to avoid circular import
    return MobilePayment.objects.filter(Q(approved=False) | Q(payment__isnull=True))


def make_approved_mobilepayment_query():
    from stregsystem.models import MobilePayment  # import locally to avoid circular import
    return MobilePayment.objects.filter(
        Q(approved=True) & Q(ignored=False) & Q(payment__isnull=True) & (
                Q(member__isnull=False) | Q(member_guess__isnull=False)))


def make_ignored_mobilepayment_query():
    from stregsystem.models import MobilePayment  # import locally to avoid circular import
    return MobilePayment.objects.filter(
        Q(approved=False) & Q(ignored=True) & Q(payment__isnull=True) & Q(member__isnull=False))


def date_to_midnight(date):
    """
    Converts a datetime.date to a datetime of the same date at midnight.

    :param date: date to convert
    :return: the date as a timezone aware datetime at midnight
    """
    return timezone.make_aware(timezone.datetime(date.year, date.month, date.day, 0, 0))


def send_payment_mail(member, amount):
    if hasattr(settings, 'TEST_MODE'):
        return
    msg = MIMEMultipart()
    msg['From'] = 'treo@fklub.dk'
    msg['To'] = member.email
    msg['Subject'] = 'Stregsystem payment'

    formatted_amount = money(amount)

    html = f"""
    <html>
        <head></head>
        <body>
            <p>
               Hej {member.firstname}!<br><br>
               Vi har indsat {formatted_amount} stregdollars på din konto: "{member.username}". <br><br>
               Hvis du ikke ønsker at modtage flere mails som denne kan du skrive en mail til: <a href="mailto:treo@fklub.dk?Subject=Klage" target="_top">treo@fklub.dk</a><br><br>
               Mvh,<br>
               TREOen<br>
               ====================================================================<br>
               Hello {member.firstname}!<br><br>
               We've inserted {formatted_amount} stregdollars on your account: "{member.username}". <br><br>
               If you do not desire to receive any more mails of this sort, please file a complaint to: <a href="mailto:treo@fklub.dk?Subject=Klage" target="_top">treo@fklub.dk</a><br><br>
               Kind regards,<br>
               TREOen
            </p>
        </body>
    </html>
    """

    msg.attach(MIMEText(html, 'html'))

    try:
        smtpObj = smtplib.SMTP('localhost', 25)
        smtpObj.sendmail('treo@fklub.dk', member.email, msg.as_string())
    except Exception as e:
        logger.error(str(e))


def parse_csv_and_create_mobile_payments(csv_file):
    def convert_timestamp(timestamp):
        """
        Get datetime object from MobilePay transaction timestamp. If not within ISO format, then make timestamp
        compliant to ISO 8601 combined date and time. This is necessary because MobilePay thinks they're cool adding
        7 decimals of precision to timestamps, however ISO 8601 only allows for 3-6 decimals of precision.
        """
        try:
            return datetime.datetime.fromisoformat(timestamp)
        except ValueError:
            try:
                # split at timezone specification, remove last digit of precision and concat
                split_timestamp = timestamp.split('+')
                timestamp = f"{split_timestamp[0][:-1]}+{split_timestamp[1]}"
                return datetime.datetime.fromisoformat(timestamp)
            except ValueError:
                raise RuntimeError(f"Could not convert transaction timestamp to ISO 8601: {timestamp}")

    imported_transactions, duplicate_transactions = 0, 0
    import csv
    # get csv reader and ignore header
    reader = csv.reader(csv_file[1:], delimiter=';', quotechar='"')
    for row in reader:

        from stregsystem.models import MobilePayment
        mobile_payment = MobilePayment(member=None, amount=row[2].replace(',', ''),
                                       timestamp=convert_timestamp(row[3]), customer_name=row[4],
                                       transaction_id=row[7], comment=row[6], payment=None)
        try:
            # unique constraint on transaction_id and payment-foreign key must hold before saving new object
            mobile_payment.validate_unique()

            # do case insensitive match on active members
            from stregsystem.models import Member
            match = Member.objects.filter(username__iexact=mobile_payment.comment.strip(), active=True)
            if match.count() == 0:
                # TODO: future work
                # no match, maybe do edit-distance checking for best match and remove common fluff such as emoji
                #  could/should be combined with a match against MobilePay-provided customer name
                pass
            elif match.count() == 1:
                mobile_payment.member = match.first()
            elif match.count() > 1:
                # something is very wrong, there should be no active users which are duplicates post PR #178
                raise RuntimeError("Duplicate usernames found at MobilePayment import. Should not exist post PR #178")
            mobile_payment.save()
            imported_transactions += 1
        except ValidationError:
            duplicate_transactions += 1
    return imported_transactions, duplicate_transactions


class stregsystemTestRunner(DiscoverRunner):
    def __init__(self, *args, **kwargs):
        settings.TEST_MODE = True
        super(stregsystemTestRunner, self).__init__(*args, **kwargs)
