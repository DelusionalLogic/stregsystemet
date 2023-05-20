from django.contrib.auth.models import User
from django.core.management import BaseCommand

from stregsystem.models import MobilePayment
from stregsystem.utils import make_unprocessed_member_filled_mobilepayment_query


class Command(BaseCommand):
    help = "Run mobilepayment matching and insert exact matches automatically"

    def handle(self, *args, **options):
        # if no payments to be processed exists, stop job
        if make_unprocessed_member_filled_mobilepayment_query().count() == 0:
            self.stdout.write(self.style.NOTICE("[autopayment] No payments to be auto-processed"))
            return

        # if logging user does not exist, stop job
        if User.objects.filter(username="autopayment").exists():
            auto_user = User.objects.get(username="autopayment")
        else:
            self.stdout.write(self.style.ERROR("[autopayment] No user 'autopayment' exists, cannot do autopayments."))
            return

        # count, approve, and submit mobilepayments
        before_count = MobilePayment.objects.filter(status=MobilePayment.APPROVED).count()
        MobilePayment.approve_member_filled_mobile_payments()
        MobilePayment.submit_correct_mobile_payments(auto_user)
        count = MobilePayment.objects.filter(status=MobilePayment.APPROVED).count() - before_count

        self.stdout.write(
            self.style.SUCCESS(f'[autopayment] Successfully submitted {count} mobilepayments automatically')
        )
