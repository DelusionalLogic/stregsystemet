import datetime
import urllib.parse
from abc import abstractmethod
from collections import Counter
from email.utils import parseaddr

from django.contrib.admin.models import LogEntry, ADDITION, CHANGE
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.db.models import Count
from django.utils import timezone

from stregsystem.caffeine import Intake, CAFFEINE_TIME_INTERVAL, current_caffeine_in_body_compound_interest
from stregsystem.deprecated import deprecated
from stregsystem.mail import send_payment_mail, send_welcome_mail
from stregsystem.templatetags.stregsystem_extras import money
from stregsystem.utils import (
    date_to_midnight,
    make_processed_mobilepayment_query,
    make_unprocessed_member_filled_mobilepayment_query,
    PaymentToolException,
)


def price_display(value):
    return money(value) + " kr."


def active_str(a):
    if a:
        return "+"
    else:
        return "-"


# Errors
class StregForbudError(Exception):
    pass


class NoMoreInventoryError(Exception):
    pass


# Create your models here.


# So we have two "basic" operations to do with money
# we can take money from a user and we can give them money
# the class names here are written from the perspective of
# the user.
# A monetary transaction, not a database transaction
class MoneyTransaction(object):
    def __init__(self, amount=0):
        self.amount = amount

    def add(self, change):
        """
        Add to the amount this transaction is for
        """
        self.amount += change

    def change(self):
        raise NotImplementedError

    def __eq__(self, other):
        """
        The equality of two transactions is based on the effect
        to the users balance
        """
        return self.change() == other.change()


class PayTransaction(MoneyTransaction):
    # The change to the users account
    # Negative because the user is losing money
    def change(self):
        """
        Returns the change to the users account
        caused by fulfilling this transaction
        """
        return -self.amount


class OrderItem(object):
    def __init__(self, product, order, count):
        self.product = product
        self.order = order
        self.count = count

    def price(self):
        return self.product.price * self.count


class Order(object):
    def __init__(self, member, room, items=None):
        self.member = member
        self.room = room
        self.created_on = timezone.now()
        self.items = items or set()  # Set to none because we don't persist

    @classmethod
    def from_products(cls, member, room, products):
        counts = Counter(products)
        order = cls(member, room)
        for product, count in counts.items():
            item = OrderItem(product=product, order=order, count=count)
            order.items.add(item)
        return order

    # @HACK In reality calculating the total for old products is way harder and
    # more complicated than this. While it's not in the database this is
    # acceptable
    def total(self):
        return sum((x.price() for x in self.items))

    @transaction.atomic
    def execute(self):
        transaction = PayTransaction(amount=self.total())

        # Check if we have enough inventory to fulfill the order
        for item in self.items:
            if item.product.start_date is not None and (item.product.bought + item.count > item.product.quantity):
                raise NoMoreInventoryError()

        # Take update lock on member row
        self.member = Member.objects.select_for_update().get(id=self.member.id)
        self.member.fulfill(transaction)

        for item in self.items:
            # @HACK Since we want to use the old database layout, we need to
            # add a sale for every item and every instance of that item
            for i in range(item.count):
                s = Sale(member=self.member, product=item.product, room=self.room, price=item.product.price)
                s.save()

            # Bought (used above) is automatically calculated, so we don't need
            # to update it
        # We changed the user balance, so save that
        self.member.save()


class GetTransaction(MoneyTransaction):
    # The change to the users account
    def change(self):
        """
        Returns the change to the users account
        caused by fulfilling this transaction
        """
        return self.amount


def get_current_year():
    return str(timezone.now().year)


class Member(models.Model):  # id automatisk...
    GENDER_CHOICES = (
        ('U', 'Unknown'),
        ('M', 'Male'),
        ('F', 'Female'),
    )
    active = models.BooleanField(default=True)

    no_whitespace_validator = RegexValidator(
        # This regex checks for whitespace in the username
        regex=r'^\S+$',
        code='invalid_username',
    )
    username = models.CharField(max_length=16, validators=[no_whitespace_validator])
    year = models.CharField(max_length=4, default=get_current_year)  # Put the current year as default
    firstname = models.CharField(max_length=20)  # for 'firstname'
    lastname = models.CharField(max_length=30)  # for 'lastname'
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    email = models.EmailField(blank=True)
    want_spam = models.BooleanField(default=True)  # oensker vedkommende fember mails?
    balance = models.IntegerField(default=0)  # hvor mange oerer vedkommende har til gode
    undo_count = models.IntegerField(default=0)  # for 'undos' i alt
    notes = models.TextField(blank=True)
    signup_due_paid = models.BooleanField(default=True)

    stregforbud_override = False

    # I don't know if this is actually used anywhere - Jesper 17/09-2017
    @deprecated
    def balance_display(self):
        return money(self.balance) + " kr."

    balance_display.short_description = "Balance"
    balance_display.admin_order_field = 'balance'

    @deprecated
    def __unicode__(self):
        return self.__str__()

    def __str__(self):
        return f"{active_str(self.active)} {self.username}: {self.firstname} {self.lastname} | {self.email} ({money(self.balance)})"

    def info_string(self) -> str:
        return f"{self.username}: {self.firstname} {self.lastname} | {self.email}"

    def signup_approved(self) -> bool:
        """
        :return: True if there's no pending signup, or it is approved.
        """
        pending_signup = PendingSignup.objects.filter(member=self).first()

        if pending_signup is None:
            return True

        return pending_signup.status == ApprovalModel.APPROVED

    def trigger_welcome_mail(self):
        if not self.signup_due_paid:
            return
        if not self.signup_approved():
            return

        send_welcome_mail(self)

    # XXX - virker ikke
    #    def get_absolute_url(self):
    #        return "/stregsystem/1/user/%i/" % self.id

    def make_payment(self, amount):
        """
        Should only be called by the Payment and MobilePayment class.

        >>> jokke = Member.objects.create(username="jokke", firstname="Joakim", lastname="Byg", email="treo@cs.aau.dk", year=2007)
        >>> jokke.balance
        0
        >>> jokke.make_payment(100)
        >>> jokke.balance
        100
        """
        self.balance = self.balance + amount

    def fulfill(self, transaction):
        """
        Fulfill the transaction
        """
        if not self.can_fulfill(transaction):
            raise StregForbudError
        self.balance += transaction.change()

    def rollback(self, transaction):
        """
        Rollback transaction
        """
        self.balance -= transaction.change()

    def can_fulfill(self, transaction):
        """
        Can the member fulfill the transaction
        """

        if self.balance + transaction.change() < 0:
            return False
        return True

        #    def clear_undo_count(self):
        #        from django.db import connection
        #        cursor = connection.cursor()
        #        cursor.execute("UPDATE stregsystem_member SET undo_count = 0 WHERE id = %s", [self.id])
        #        return

    def has_stregforbud(self, buy=0):
        # hyttetur, julefrokost, paaskefrokost override
        # if buy == 30000 or buy == 27000 or buy == 25000 or buy == 17500 or buy == 1500 or buy == 3500 or buy == 10000 or buy == 33300 or buy == 22200:
        #    return False
        if Member.stregforbud_override:
            return False

        return self.balance - buy < 0

    # BAC in this method stands for "Blood alcohol content"
    def calculate_alcohol_promille(self):
        from stregsystem.booze import alcohol_bac_timeline, Gender
        from datetime import timedelta

        now = timezone.now()
        # Lets assume noone is drinking 12 hours straight
        calculation_start = now - timedelta(hours=12)

        alcohol_sales = self.sale_set.filter(
            timestamp__gt=calculation_start, product__alcohol_content_ml__gt=0.0
        ).order_by('timestamp')
        alcohol_timeline = [(s.timestamp, s.product.alcohol_content_ml) for s in alcohol_sales]

        gender = Gender.UNKNOWN
        if self.gender == "M":
            gender = Gender.MALE
        elif self.gender == "F":
            gender = Gender.FEMALE

        bac = alcohol_bac_timeline(gender, 80, now, alcohol_timeline)

        # Tihi:
        drunken_bastards = {
            2219: 42.0,  # mbogh
            2124: -1.5,  # mchro
            2113: 42.0,  # kyrke
            2024: 31.5,  # jbr
            2414: 5440,  # kkkas
        }
        bac += drunken_bastards.get(self.id, 0.0)

        return bac

    def calculate_caffeine_in_body(self) -> float:
        # get list of last 24h caffeine intakes and calculate current body caffeine content
        return current_caffeine_in_body_compound_interest(
            [
                Intake(x.timestamp, x.product.caffeine_content_mg)
                for x in self.sale_set.filter(
                    timestamp__gt=timezone.now() - CAFFEINE_TIME_INTERVAL, product__caffeine_content_mg__gt=0
                ).order_by('timestamp')
            ]
        )

    def is_leading_coffee_addict(self):
        coffee_category = [6]

        now = timezone.now()
        start_of_week = now - datetime.timedelta(days=now.weekday()) - datetime.timedelta(hours=now.hour)
        user_with_most_coffees_bought = (
            Member.objects.filter(
                sale__timestamp__gt=start_of_week,
                sale__timestamp__lte=now,
                sale__product__categories__in=coffee_category,
            )
            .annotate(Count('sale'))
            .order_by('-sale__count', 'username')
            .first()
        )

        return user_with_most_coffees_bought == self


class Payment(models.Model):  # id automatisk...
    class Meta:
        permissions = (("import_batch_payments", "Import batch payments"),)

    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    amount = models.IntegerField()  # penge, oere...
    notes = models.TextField(blank=True)

    @deprecated
    def amount_display(self):
        return money(self.amount) + " kr."

    amount_display.short_description = "Amount"
    # XXX - django bug - kan ikke vaelge mellem desc og asc i admin, som ved normalt felt
    amount_display.admin_order_field = '-amount'

    @deprecated
    def __unicode__(self):
        return self.__str__()

    def __str__(self):
        return self.member.username + " " + str(self.timestamp) + ": " + money(self.amount)

    @transaction.atomic
    def save(self, mbpayment=None, *args, **kwargs):
        if self.id:
            return  # update -- should not be allowed
        else:
            self.member.make_payment(self.amount)
            super(Payment, self).save(*args, **kwargs)
            self.member.save()
            if self.member.email != "" and self.amount != 0:
                if '@' in parseaddr(self.member.email)[1] and self.member.want_spam:
                    send_payment_mail(self.member, self.amount, mbpayment.comment if mbpayment else None)

    def log_from_mobile_payment(self, processed_mobile_payment, admin_user: User):
        LogEntry.objects.log_action(
            user_id=admin_user.pk,
            content_type_id=ContentType.objects.get_for_model(Payment).pk,
            object_id=self.id,
            object_repr=str(self),
            action_flag=ADDITION,
            change_message=f"{''}" f"MobilePayment (transaction_id: {processed_mobile_payment.transaction_id})",
        )

    @transaction.atomic
    def delete(self, *args, **kwargs):
        if self.id:
            self.member.make_payment(-self.amount)
            super(Payment, self).delete(*args, **kwargs)
            self.member.save()
        else:
            super(Payment, self).delete(*args, **kwargs)


class ApprovalModel(models.Model):
    class Meta:
        abstract = True

    UNSET = 'U'
    APPROVED = 'A'
    IGNORED = 'I'
    REJECTED = 'R'

    STATUS_CHOICES = (
        (UNSET, 'Unset'),
        (APPROVED, 'Approved'),
        (IGNORED, 'Ignored'),
        (REJECTED, 'Rejected'),
    )

    status = models.CharField(max_length=1, choices=STATUS_CHOICES, default=UNSET)

    def approve(self):
        self.status = ApprovalModel.APPROVED
        self.save()

    def reject(self):
        self.status = ApprovalModel.REJECTED
        self.save()

    def ignore(self):
        self.status = ApprovalModel.IGNORED
        self.save()

    def log_approval(self, admin_user: User, msg):
        LogEntry.objects.log_action(
            user_id=admin_user.pk,
            content_type_id=ContentType.objects.get_for_model(type(self)).pk,
            object_id=self.id,
            object_repr=str(self),
            action_flag=CHANGE,
            change_message=msg,
        )

    @classmethod
    @abstractmethod
    def process_submitted(cls, submitted_data, admin_user: User):
        pass


class MobilePayment(ApprovalModel):
    class Meta:
        permissions = (("mobilepaytool_access", "MobilePaytool access"),)

    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, null=True, blank=True
    )  # nullable as mobile payment may not have match yet
    payment = models.OneToOneField(
        Payment, on_delete=models.CASCADE, null=True, blank=True, unique=True
    )  # Django does not consider null == null, so this works
    customer_name = models.CharField(max_length=64, null=True, blank=True)
    timestamp = models.DateTimeField()
    amount = models.IntegerField()
    transaction_id = models.CharField(
        max_length=32, unique=True
    )  # trans_ids are at most 17 chars, assumed to be unique
    comment = models.CharField(max_length=128, blank=True, null=True)

    def __str__(self):
        return (
            f"{self.member.username if self.member is not None else 'Not assigned'}, {self.customer_name}, "
            f"{self.timestamp}, {self.amount}, {self.transaction_id}, {self.comment}"
        )

    @transaction.atomic()
    def delete(self, *args, **kwargs):
        if self.id and self.payment is not None:
            self.member.make_payment(-self.amount)
            super(MobilePayment, self).delete(*args, **kwargs)
            self.member.save()
        else:
            super(MobilePayment, self).delete(*args, **kwargs)

    @staticmethod
    def submit_all_processed_mobile_payments(admin_user: User):
        processed_mobile_payment: MobilePayment  # annotate iterated variable (PEP 526)
        for processed_mobile_payment in make_processed_mobilepayment_query():
            processed_mobile_payment.submit_processed_mobile_payment(admin_user)

    @transaction.atomic
    def submit_processed_mobile_payment(self, admin_user: User):
        if self.status == ApprovalModel.APPROVED:
            if not self.member.signup_due_paid:
                signup = PendingSignup.objects.get(member=self.member)
                signup.pay_towards_due(self)
            else:
                payment = Payment(member=self.member, amount=self.amount)
                # Save payment and foreign key to MobilePayment field
                payment.save(mbpayment=self)
                payment.log_from_mobile_payment(self, admin_user)
                self.payment = payment
                self.save()
        elif self.status == ApprovalModel.IGNORED:
            self.log_approval(admin_user, "Ignored")

    @classmethod
    @transaction.atomic
    def process_submitted(cls, submitted_data, admin_user: User):
        """
        Takes a cleaned_form from a PaymentToolFormSet and processes them.
        The return value is the number of rows procesed.
        If one of the MobilePayments have been altered compared to the data, a RuntimeError will be raised.
        """
        cleaned_data = []

        for row in submitted_data:
            # Skip rows which are set to "unset" (the default).
            if row['status'] == ApprovalModel.UNSET:
                continue
            # Skip rows which are set to "approved" without member. A Payment MUST have a Member.
            if row['status'] == ApprovalModel.APPROVED and row['member'] is None:
                continue
            cleaned_data.append(row)

        # Find the id's of the remaining cleaned data.
        mobile_payment_ids = [row['id'].id for row in cleaned_data]
        # Count how many id of the id's who are set to status "unset".
        database_mobile_payment_count = MobilePayment.objects.filter(
            id__in=mobile_payment_ids, status=ApprovalModel.UNSET
        ).count()
        # If there's a discrepancy in the number of rows, the user must have an outdated image. Throw an error.
        if len(mobile_payment_ids) != database_mobile_payment_count:
            # get database mobilepayments matching cleaned ids and having been processed while form has been active
            raise PaymentToolException(
                MobilePayment.objects.filter(
                    id__in=mobile_payment_ids, status__in=(ApprovalModel.APPROVED, ApprovalModel.IGNORED)
                )
            )

        for row in cleaned_data:
            processed_mobile_payment = MobilePayment.objects.get(id=row['id'].id)
            # If approved, we need to create a payment and relate said payment to the mobilepayment.
            processed_mobile_payment.status = row['status']
            processed_mobile_payment.member = Member.objects.get(id=row['member'].id)
            processed_mobile_payment.submit_processed_mobile_payment(admin_user)
            processed_mobile_payment.save()

        # Return how many records were modified.
        return len(mobile_payment_ids)

    @staticmethod
    def approve_member_filled_mobile_payments():
        for payment in make_unprocessed_member_filled_mobilepayment_query():
            if payment.status == ApprovalModel.UNSET:
                payment.approve()


class Category(models.Model):
    name = models.CharField(max_length=64)

    def __unicode__(self):
        return self.__str__()

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Categories'


# XXX
class Room(models.Model):
    name = models.CharField(max_length=64)
    description = models.CharField(max_length=64)
    notes = models.TextField(blank=True)

    @deprecated
    def __unicode__(self):
        return self.__str__()

    def __str__(self):
        return self.name


class Product(models.Model):  # id automatisk...
    name = models.CharField(max_length=64)
    name_style = models.TextField(
        max_length=64,
        blank=True,
        help_text="If product is very cool, usually something like: font-size: 2em; font-weight: bold; color: red; margin: 1em 0;",
    )
    description = models.CharField(max_length=64, blank=True)
    price = models.IntegerField()  # penge, oere...
    active = models.BooleanField()
    start_date = models.DateField(blank=True, null=True)
    quantity = models.IntegerField(default=0)
    deactivate_date = models.DateTimeField(blank=True, null=True)
    categories = models.ManyToManyField(Category, blank=True)
    rooms = models.ManyToManyField(Room, blank=True)
    alcohol_content_ml = models.FloatField(default=0.0, null=True)
    caffeine_content_mg = models.IntegerField(default=0)

    @deprecated
    def __unicode__(self):
        return self.__str__()

    def __str__(self):
        return active_str(self.active) + " " + self.name + " (" + money(self.price) + ")"

    def save(self, *args, **kwargs):
        price_changed = True
        if self.id:
            try:
                oldprice = self.old_prices.order_by('-changed_on')[0:1].get()
                price_changed = oldprice != self.price
            except OldPrice.DoesNotExist:  # der findes varer hvor der ikke er nogen "tidligere priser"
                pass
        super(Product, self).save(*args, **kwargs)
        if price_changed:
            OldPrice.objects.create(product=self, price=self.price)

    @property
    def bought(self):
        # @INCOMPLETE: If it's an unlimited item we just don't care about the
        # bought count - Jesper 27/09-2017
        if self.start_date is None:
            return 0
        return self.sale_set.filter(timestamp__gt=date_to_midnight(self.start_date)).aggregate(bought=Count("id"))[
            "bought"
        ]

    def is_active(self):
        expired = self.deactivate_date is not None and self.deactivate_date <= timezone.now()

        if self.start_date is not None:
            out_of_stock = self.quantity <= self.bought
        else:
            # Items without a startdate is never out of stock
            out_of_stock = False

        return self.active and not expired and not out_of_stock


class ProductNote(models.Model):
    """A tag that can be assigned to products.

    Model for notes about a product, which should be visible in a certain range of time.
    Such as a note stating that the product is new for the first couple of weeks.
    """

    products = models.ManyToManyField(Product)
    rooms = models.ManyToManyField(Room, blank=True)
    text = models.TextField()
    active = models.BooleanField(default=True)
    background_color = models.CharField(
        max_length=20, help_text="Write a valid html color", default="yellow"
    )  # If anyone wants to use LightGoldenRodYellow, they can
    text_color = models.CharField(max_length=20, help_text="Write a valid html color", default="black")
    start_date = models.DateField()
    end_date = models.DateField()
    comment = models.TextField(blank=True)

    def __str__(self):
        return self.text + " (" + " | ".join(str(x.name) for x in self.products.all()) + ")"


class NamedProduct(models.Model):
    name = models.CharField(max_length=50, unique=True, validators=[RegexValidator(regex=r'^[^\d:\-_][\w\-]+$')])
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='named_id')

    def __str__(self):
        return self.name

    def map_str(self):
        return self.name + " -> " + str(self.product.id)


class OldPrice(models.Model):  # gamle priser, skal huskes; til regnskab/statistik?
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='old_prices')
    price = models.IntegerField()  # penge, oere...
    changed_on = models.DateTimeField(auto_now_add=True)

    @deprecated
    def __unicode__(self):
        return self.__str__()

    def __str__(self):
        return self.product.name + ": " + money(self.price) + " (" + str(self.changed_on) + ")"


class Sale(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    price = models.IntegerField()

    class Meta:
        index_together = [
            ["product", "timestamp"],
        ]

        permissions = (("access_sales_reports", "Can access sales reports"),)

    def price_display(self):
        return money(self.price) + " kr."

    price_display.short_description = "Price"
    # XXX - django bug - kan ikke vaelge mellem desc og asc i admin, som ved normalt felt
    price_display.admin_order_field = 'price'

    @deprecated
    def __unicode__(self):
        return self.__str__()

    def __str__(self):
        return self.member.username + " " + self.product.name + " (" + money(self.price) + ") " + str(self.timestamp)

    def save(self, *args, **kwargs):
        if self.id:
            raise RuntimeError("Updates of sales are not allowed")
        super(Sale, self).save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.id:
            super(Sale, self).delete(*args, **kwargs)
        else:
            raise RuntimeError("You can't delete a sale that hasn't happened")


# XXX
class News(models.Model):
    title = models.CharField(max_length=64)
    text = models.TextField()
    pub_date = models.DateTimeField()
    stop_date = models.DateTimeField()

    class Meta:
        verbose_name_plural = "News"

    @deprecated
    def __unicode__(self):
        return self.__str__()

    def __str__(self):
        return self.title + " -- " + str(self.pub_date)


class PendingSignup(ApprovalModel):
    class Meta:
        permissions = (("signuptool_access", "Sign-up Tool access"),)

    member = models.ForeignKey(Member, on_delete=models.CASCADE, null=False)
    due = models.IntegerField(default=200 * 100)

    def generate_mobilepay_url(self):
        comment = self.member.username
        query = {'phone': '90601', 'comment': comment, 'amount': "{0:.2f}".format(self.due / 100.0)}
        return 'mobilepay://send?{}'.format(urllib.parse.urlencode(query))

    def __str__(self):
        return (
            f"{self.member.info_string() if self.member is not None else 'Not assigned'}, "
            f"{self.due}, {self.member.notes}"
        )

    @transaction.atomic
    def complete(self, payment: MobilePayment):
        """
        Triggered when due has been paid
        """
        # If the user payed more than their due add it to their balance
        if self.due <= 0:
            payment.payment = Payment.objects.create(member=self.member, amount=-self.due)
        payment.save()

        self.member.signup_due_paid = True
        self.member.save()

        # Only delete Pending Signup if approved.
        if self.status == ApprovalModel.APPROVED:
            self.member.trigger_welcome_mail()
            self.delete()
        else:
            self.save()

    @transaction.atomic
    def pay_towards_due(self, payment: MobilePayment):
        self.due -= payment.amount
        payment.status = MobilePayment.APPROVED

        # If their due has been payed activate the user and delete the signup object
        if self.due <= 0:
            self.complete(payment)
        else:
            payment.payment = Payment.objects.create(member=self.member, amount=0)
            payment.save()
            self.save()

    @classmethod
    @transaction.atomic
    def process_submitted(cls, submitted_data, admin_user: User):
        """
        Takes a cleaned_form from a SignupToolFormSet and processes them.
        The return value is the number of rows procesed.
        If one of the MobilePayments have been altered compared to the data, a RuntimeError will be raised.
        """
        cleaned_data = []

        for row in submitted_data:
            # Skip rows which are set to "unset" (the default).
            if row['status'] == ApprovalModel.UNSET:
                continue

            cleaned_data.append(row)

        # Find the id's of the remaining cleaned data.
        pending_signup_ids = [row['id'].id for row in cleaned_data]

        # Count how many id of the id's who are set to status "unset".
        database_approval_count = PendingSignup.objects.filter(
            id__in=pending_signup_ids, status=ApprovalModel.UNSET
        ).count()

        # If there's a discrepancy in the number of rows, the user must have an outdated image. Throw an error.
        if len(pending_signup_ids) != database_approval_count:
            # get database mobilepayments matching cleaned ids and having been processed while form has been active
            raise PaymentToolException(
                PendingSignup.objects.filter(
                    id__in=pending_signup_ids, status__in=(ApprovalModel.APPROVED, ApprovalModel.IGNORED)
                )
            )

        for row in cleaned_data:
            processed_signup = PendingSignup.objects.get(id=row['id'].id)

            if row['status'] == ApprovalModel.APPROVED:
                processed_signup.log_approval(admin_user, "Approved")
            elif row['status'] == ApprovalModel.IGNORED:
                processed_signup.log_approval(admin_user, "Ignored")
            elif row['status'] == ApprovalModel.REJECTED:
                processed_signup.log_approval(admin_user, "Rejected")

            processed_signup.status = row['status']
            processed_signup.save()

            # Trigger welcome mail if sign-up is also paid.
            processed_signup.member.trigger_welcome_mail()

        # Return how many records were modified.
        return len(pending_signup_ids)


class Theme(models.Model):
    name = models.CharField("Name", max_length=50)
    html = models.CharField("HTML filename", max_length=50, blank=True, default="")
    css = models.CharField("CSS filename", max_length=50, blank=True, default="")
    js = models.CharField("JS filename", max_length=50, blank=True, default="")
    begin_month = models.PositiveSmallIntegerField("Begin month")
    begin_day = models.PositiveSmallIntegerField("Begin day", default=1)
    end_month = models.PositiveSmallIntegerField("End month")
    end_day = models.PositiveSmallIntegerField("End day", default=31)

    NONE = "N"
    SHOW = "S"
    HIDE = "H"
    OVERRIDE_CHOICES = (
        (NONE, "None"),
        (SHOW, "Force show"),
        (HIDE, "Force hide"),
    )
    override = models.CharField("Override", max_length=1, choices=OVERRIDE_CHOICES, default=NONE)

    class Meta:
        ordering = ["begin_month", "begin_day"]

    def __str__(self):
        return self.name
