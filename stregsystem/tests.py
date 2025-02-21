# -*- coding: utf-8 -*-
import datetime
from collections import Counter
from copy import deepcopy
from unittest import mock
from unittest.mock import patch, MagicMock

import pytz
from django.utils.dateparse import parse_datetime
import stregsystem.parser as parser
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.contrib.admin.sites import AdminSite
from django.contrib.messages import get_messages
from django.forms import model_to_dict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from stregreport import views
from stregsystem import admin
from stregsystem import views as stregsystem_views
from stregsystem.admin import CategoryAdmin, ProductAdmin, MemberForm, MemberAdmin
from stregsystem.booze import ballmer_peak
from stregsystem.caffeine import CAFFEINE_DEGRADATION_PR_HOUR, CAFFEINE_IN_COFFEE
from stregsystem.models import (
    Category,
    GetTransaction,
    Member,
    NoMoreInventoryError,
    Order,
    OrderItem,
    Payment,
    PayTransaction,
    Product,
    Room,
    Sale,
    StregForbudError,
    active_str,
    price_display,
    MobilePayment,
    PendingSignup,
    NamedProduct,
    ApprovalModel,
    ProductNote,
)
from stregsystem.purchase_heatmap import prepare_heatmap_template_context
from stregsystem.templatetags.stregsystem_extras import caffeine_emoji_render
from stregsystem.utils import mobile_payment_exact_match_member, strip_emoji, PaymentToolException
from stregsystem.mail import data_sent


def assertCountEqual(case, *args, **kwargs):
    try:
        case.assertCountEqual(*args, **kwargs)
    except AttributeError:
        case.assertItemsEqual(*args, **kwargs)


class ModelMiscTests(TestCase):
    def test_price_display_none(self):
        v = price_display(None)
        self.assertEqual(v, "0.00 kr.")

    def test_price_display_zero(self):
        v = price_display(0)
        self.assertEqual(v, "0.00 kr.")

    def test_price_display_one(self):
        v = price_display(1)
        self.assertEqual(v, "0.01 kr.")

    def test_price_display_hundred(self):
        v = price_display(100)
        self.assertEqual(v, "1.00 kr.")

    def test_active_str_true(self):
        v = active_str(True)
        self.assertEqual(v, "+")

    def test_active_str_false(self):
        v = active_str(False)
        self.assertEqual(v, "-")


class SaleViewTests(TestCase):
    fixtures = ["initial_data"]

    def test_make_sale_letter_quickbuy(self):
        response = self.client.post(reverse('quickbuy', args="1"), {"quickbuy": "jokke a"})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed("stregsystem/error_invalidquickbuy.html")

    @patch('stregsystem.models.Member.can_fulfill')
    @patch('stregsystem.models.Member.fulfill')
    def test_make_sale_quickbuy_success_for_multiple_named_product(self, fulfill, can_fulfill):
        can_fulfill.return_value = True
        item = Product.objects.get(id=1)
        NamedProduct.objects.create(name='test1', product=item)

        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": "jokke test1:2"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "stregsystem/index_sale.html")

        assertCountEqual(self, response.context["products"], [('Limfjordsporter', 2)])
        self.assertEqual(response.context["member"], Member.objects.get(username="jokke"))

        fulfill.assert_called_once_with(PayTransaction(1800))

    @patch('stregsystem.models.Member.can_fulfill')
    @patch('stregsystem.models.Member.fulfill')
    def test_make_sale_quickbuy_success_for_named_product(self, fulfill, can_fulfill):
        can_fulfill.return_value = True
        item = Product.objects.get(id=1)
        NamedProduct.objects.create(name='test1', product=item)

        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": "jokke test1"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "stregsystem/index_sale.html")

        assertCountEqual(self, response.context["products"], {('Limfjordsporter', 1)})
        self.assertEqual(response.context["member"], Member.objects.get(username="jokke"))

        fulfill.assert_called_once_with(PayTransaction(900))

    @patch('stregsystem.models.Member.can_fulfill')
    @patch('stregsystem.models.Member.fulfill')
    def test_make_sale_quickbuy_success(self, fulfill, can_fulfill):
        can_fulfill.return_value = True

        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": "jokke 1"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "stregsystem/index_sale.html")

        assertCountEqual(self, response.context["products"], {('Limfjordsporter', 1)})
        self.assertEqual(response.context["member"], Member.objects.get(username="jokke"))

        fulfill.assert_called_once_with(PayTransaction(900))

    def test_quickbuy_member_case_is_insensitive(self):
        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": "jokke"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "stregsystem/menu.html")

        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": "JOKKE"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "stregsystem/menu.html")

    def test_make_sale_quickbuy_wrong_product_for_named_product(self):
        item = Product.objects.get(id=1)
        NamedProduct.objects.create(name='test1', product=item)

        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": "jokke gnu99"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "stregsystem/error_invalidquickbuy.html")

    def test_create_named_product_fails_for_invalid_name(self):
        item = Product.objects.get(id=1)
        prod = NamedProduct(name='11', product=item)
        with self.assertRaises(ValidationError):
            prod.full_clean()

    def test_create_named_product_fails_for_invalid_name_2(self):
        item = Product.objects.get(id=1)
        prod = NamedProduct(name='test øl', product=item)
        with self.assertRaises(ValidationError):
            prod.full_clean()

    def test_create_named_product_fails_for_invalid_name_3(self):
        item = Product.objects.get(id=1)
        prod = NamedProduct(name='øl:2', product=item)
        with self.assertRaises(ValidationError):
            prod.full_clean()

    def test_create_named_product_fails_for_invalid_name_4(self):
        item = Product.objects.get(id=1)
        prod = NamedProduct(name='', product=item)
        with self.assertRaises(ValidationError):
            prod.full_clean()

    def test_create_named_product_succeed_for_valid_name(self):
        item = Product.objects.get(id=1)
        prod = NamedProduct(name='øl', product=item)
        prod.full_clean()

    def test_create_named_product_succeed_for_valid_name_2(self):
        item = Product.objects.get(id=1)
        prod = NamedProduct(name='monster-mango', product=item)
        prod.full_clean()

    def test_create_named_product_succeed_for_valid_name_3(self):
        item = Product.objects.get(id=1)
        prod = NamedProduct(name='ale16', product=item)
        prod.full_clean()

    def test_create_named_product_succeed_for_valid_name_4(self):
        item = Product.objects.get(id=1)
        prod = NamedProduct(name='månedens-øl', product=item)
        prod.full_clean()

    def test_make_sale_quickbuy_fail(self):
        member_username = 'jan'
        member_before = Member.objects.get(username=member_username)
        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": member_username + " 1"})
        member_after = Member.objects.get(username=member_username)

        self.assertEqual(response.status_code, 402)
        self.assertTemplateUsed(response, "stregsystem/error_stregforbud.html")
        self.assertEqual(member_before.balance, member_after.balance)

        self.assertEqual(response.context["member"], Member.objects.get(username=member_username))

    def test_make_sale_quickbuy_wrong_product(self):
        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": "jokke 99"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "stregsystem/error_productdoesntexist.html")

    @patch('stregsystem.models.Member.can_fulfill')
    def test_make_sale_menusale_fail(self, can_fulfill):
        can_fulfill.return_value = False
        member_id = 1
        member_before = Member.objects.get(id=member_id)

        response = self.client.post(reverse('menu', args=(1, member_id)), data={'product_id': 1})

        member_after = Member.objects.get(id=member_id)

        self.assertEqual(member_before.balance, member_after.balance)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "stregsystem/error_stregforbud.html")
        self.assertEqual(response.context["member"], Member.objects.get(id=1))

    @patch('stregsystem.models.Member.can_fulfill')
    @patch('stregsystem.models.Member.fulfill')
    def test_make_sale_menusale_success(self, fulfill, can_fulfill):
        can_fulfill.return_value = True

        response = self.client.post(reverse('menu', args=(1, 1)), data={'product_id': 1})
        self.assertTemplateUsed(response, "stregsystem/menu.html")

        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.context["bought"], Product.objects.get(id=1))
        self.assertEqual(response.context["member"], Member.objects.get(id=1))

        fulfill.assert_called_once_with(PayTransaction(900))

    def test_quicksale_has_status_line(self):
        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": "jokke 1"})

        self.assertContains(
            response,
            "<b><span class=\"username\">jokke</span> har lige købt 1 Limfjordsporter for tilsammen " "9.00 kr.</b>",
            html=True,
        )

    def test_usermenu(self):
        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": "jokke"})

        self.assertTemplateUsed(response, "stregsystem/menu.html")

    def test_quickbuy_empty(self):
        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": ""})

        self.assertTemplateUsed(response, "stregsystem/index.html")

    def test_index(self):
        response = self.client.post(reverse('index'))

        # Assert permanent redirect
        self.assertEqual(response.status_code, 301)

    def test_menu_index(self):
        response = self.client.post(reverse('menu_index', args=(1,)))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "stregsystem/index.html")
        # Assert that the index screen at least contains one of the products in
        # the database. Technically this doesn't check everything exhaustively,
        # but it's better than nothing -Jesper 18/09-2017
        self.assertContains(response, "Limfjordsporter")
        self.assertNotContains(response, "NonExistentProduct")

    def test_quickbuy_no_known_member(self):
        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": "notinthere"})

        self.assertTemplateUsed(response, "stregsystem/error_usernotfound.html")

    def test_quicksale_increases_bought(self):
        before = Product.objects.get(id=2)
        before_bought = before.bought
        before_member = Member.objects.get(username="jokke")

        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": "jokke 2"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "stregsystem/index_sale.html")

        after = Product.objects.get(id=2)
        after_member = Member.objects.get(username="jokke")

        self.assertEqual(before_bought + 1, after.bought)
        # 900 is the product price
        self.assertEqual(before_member.balance - 900, after_member.balance)

    def test_quicksale_quanitity_none_noincrease(self):
        before = Product.objects.get(id=1)
        before_member = Member.objects.get(username="jokke")

        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": "jokke 1"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "stregsystem/index_sale.html")

        after = Product.objects.get(id=1)
        after_member = Member.objects.get(username="jokke")

        self.assertEqual(before.bought, after.bought)
        # 900 is the product price
        self.assertEqual(before_member.balance - 900, after_member.balance)

    def test_quicksale_out_of_stock(self):
        before = Product.objects.get(id=1)
        before_member = Member.objects.get(username="jokke")

        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": "jokke 3"})

        self.assertEqual(response.status_code, 200)
        # I don't know which template to use (I should probably make one). So
        # for now let's just make sure that we at least don't use the one that
        # says "correct" - Jesper 14/09-2017
        self.assertTemplateNotUsed(response, "stregsystem/index_sale.html")

        after = Product.objects.get(id=1)
        after_member = Member.objects.get(username="jokke")

        self.assertEqual(before.bought, after.bought)
        self.assertEqual(before_member.balance, after_member.balance)

    def test_quicksale_product_not_in_room(self):
        before_product = Product.objects.get(id=4)
        before_member = Member.objects.get(username="jokke")

        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": "jokke 4"})

        after_product = Product.objects.get(id=4)
        after_member = Member.objects.get(username="jokke")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "stregsystem/error_productdoesntexist.html")

        self.assertEqual(before_product.bought, after_product.bought)
        self.assertEqual(before_member.balance, after_member.balance)

    def test_quicksale_product_available_all_rooms(self):
        before_product = Product.objects.get(id=1)
        before_member = Member.objects.get(username="jokke")

        response = self.client.post(reverse('quickbuy', args=(1,)), {"quickbuy": "jokke 1"})

        after_product = Product.objects.get(id=1)
        after_member = Member.objects.get(username="jokke")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "stregsystem/index_sale.html")

        self.assertEqual(before_member.balance - 900, after_member.balance)

    def test_menusale_product_not_in_room(self):
        before_product = Product.objects.get(id=4)
        before_member = Member.objects.get(username="jokke")

        response = self.client.post(reverse('menu', args=(1, before_member.id)), data={'product_id': 4})

        after_product = Product.objects.get(id=4)
        after_member = Member.objects.get(username="jokke")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "stregsystem/menu.html")

        self.assertEqual(before_product.bought, after_product.bought)
        self.assertEqual(before_member.balance, after_member.balance)

    def test_multibuy_hint_not_applicable(self):
        member = Member.objects.get(username="jokke")
        give_multibuy_hint, sale_hints = stregsystem_views._multibuy_hint(timezone.now(), member)
        self.assertFalse(give_multibuy_hint)
        self.assertIsNone(sale_hints)

    def test_multibuy_hint_one_buy_not_applicable(self):
        member = Member.objects.get(username="jokke")
        coke = Product.objects.create(name="coke", price=100, active=True)
        Sale.objects.create(
            member=member,
            product=coke,
            price=100,
        )
        give_multibuy_hint, sale_hints = stregsystem_views._multibuy_hint(timezone.now(), member)
        self.assertFalse(give_multibuy_hint)
        self.assertIsNone(sale_hints)

    def test_multibuy_hint_two_buys_applicable(self):
        member = Member.objects.get(username="jokke")
        coke = Product.objects.create(name="coke", price=100, active=True)
        with freeze_time(timezone.datetime(2018, 1, 1)) as frozen_time:
            for i in range(1, 3):
                Sale.objects.create(
                    member=member,
                    product=coke,
                    price=100,
                )
                frozen_time.tick()
        give_multibuy_hint, sale_hints = stregsystem_views._multibuy_hint(
            timezone.datetime(2018, 1, 1, tzinfo=pytz.UTC), member
        )
        self.assertTrue(give_multibuy_hint)
        self.assertEqual(sale_hints, "{} {}:{}".format("<span class=\"username\">jokke</span>", coke.id, 2))


class UserInfoViewTests(TestCase):
    def setUp(self):
        self.room = Room.objects.create(name="test")
        self.jokke = Member.objects.create(username="jokke")
        self.coke = Product.objects.create(name="coke", price=100, active=True)
        self.flan = Product.objects.create(name="flan", price=200, active=True)
        self.sales = []
        with freeze_time(timezone.datetime(2000, 1, 1)) as frozen_time:
            for i in range(1, 4):
                self.sales.append(
                    Sale.objects.create(
                        member=self.jokke,
                        product=self.coke,
                        price=100,
                    )
                )
                frozen_time.tick()
        self.payments = []
        with freeze_time(timezone.datetime(2000, 1, 1)) as frozen_time:
            for i in range(1, 3):
                self.payments.append(
                    Payment.objects.create(
                        member=self.jokke,
                        amount=100,
                    )
                )
                frozen_time.tick()

    def test_renders(self):
        response = self.client.post(
            reverse('userinfo', args=(self.room.id, self.jokke.id)),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "stregsystem/menu_userinfo.html")

    def test_last_sale(self):
        response = self.client.post(
            reverse('userinfo', args=(self.room.id, self.jokke.id)),
        )

        self.assertSequenceEqual(response.context["last_sale_list"], self.sales[::-1])

    def test_last_payment(self):
        response = self.client.post(
            reverse('userinfo', args=(self.room.id, self.jokke.id)),
        )

        self.assertEqual(response.context["last_payment"], self.payments[-1])

    # @INCOMPLETE: Strictly speaking there are two more variables here. Are
    # they actually necessary, since we don't allow people to go negative
    # anymore anyway? - Jesper 18/09-2017


class PurchaseHeatmapTests(TestCase):
    def setUp(self):
        self.room = Room.objects.create(name="test")
        self.jokke = Member.objects.create(username="jokke")
        self.coke = Product.objects.create(name="coke", price=100, active=True)
        self.flan = Product.objects.create(name="flan", price=200, active=True)
        self.sales = []
        self.payments = []

    def test_empty_user(self):
        with freeze_time(timezone.datetime(2000, 1, 1)) as frozen_time:
            heatmap_context = prepare_heatmap_template_context(self.jokke, 5, datetime.date.today())

        for weekday_header, rows in heatmap_context['rows']:
            for row_data in rows:
                self.assertEqual(len(row_data.products), 0)

    def test_weeks_correct(self):
        with freeze_time(timezone.datetime(2000, 1, 1)) as frozen_time:
            heatmap_context = prepare_heatmap_template_context(self.jokke, 5, datetime.date.today())

            self.assertEqual(heatmap_context['column_labels'], ['48', '49', '50', '51', '52'])

    def test_user_with_some_purchases(self):
        # TODO: Do test methods endure side-effects ? Or do they reset.
        with freeze_time(timezone.datetime(2000, 1, 1)) as frozen_time:
            for i in range(1, 4):
                self.sales.append(
                    Sale.objects.create(
                        member=self.jokke,
                        product=self.coke,
                        price=100,
                    )
                )
                frozen_time.tick()

            frozen_time.tick(datetime.timedelta(days=1))
            heatmap_context = prepare_heatmap_template_context(self.jokke, 5, datetime.date.today())

            found_date = False

            for weekday_header, rows in heatmap_context['rows']:
                for row_data in rows:
                    if str(row_data.date) == "2000-01-01":
                        found_date = True
                        self.assertEqual(len(row_data.products), 3)
                    else:
                        self.assertEqual(len(row_data.products), 0)

            self.assertEqual(found_date, True)

        self.sales.clear()


class TransactionTests(TestCase):
    def test_pay_transaction_change_neg(self):
        transaction = PayTransaction(100)
        self.assertEqual(transaction.change(), -100)

    def test_pay_transaction_add(self):
        transaction = PayTransaction(90)
        transaction.add(10)
        self.assertEqual(transaction.change(), -100)

    def test_get_transaction_change_pos(self):
        transaction = GetTransaction(100)
        self.assertEqual(transaction.change(), 100)

    def test_get_transaction_change_add(self):
        transaction = GetTransaction(90)
        transaction.add(10)
        self.assertEqual(transaction.change(), 100)


class OrderTest(TestCase):
    def setUp(self):
        self.member = Member.objects.create(balance=100)
        self.room = Room.objects.create(name="room")
        self.product = Product.objects.create(
            id=1,
            name="øl",
            price=10,
            active=True,
        )

    def test_order_fromproducts(self):
        products = [
            self.product,
            self.product,
        ]
        order = Order.from_products(self.member, self.room, products)
        self.assertEqual(list(Counter(products).items()), [(item.product, item.count) for item in order.items])

    def test_order_total_single_item(self):
        order = Order(self.member, self.room)

        item = OrderItem(self.product, order, 1)
        order.items.add(item)

        self.assertEqual(order.total(), 10)

    def test_order_total_multi_item(self):
        order = Order(self.member, self.room)

        item = OrderItem(self.product, order, 2)
        order.items.add(item)

        self.assertEqual(order.total(), 20)

    @patch('stregsystem.models.Member.fulfill')
    def test_order_execute_single_transaction(self, fulfill):
        order = Order(self.member, self.room)

        item = OrderItem(self.product, order, 1)
        order.items.add(item)

        order.execute()

        fulfill.assert_called_once_with(PayTransaction(10))

    @patch('stregsystem.models.Member.fulfill')
    def test_order_execute_multi_transaction(self, fulfill):
        order = Order(self.member, self.room)

        item = OrderItem(self.product, order, 2)
        order.items.add(item)

        order.execute()

        fulfill.assert_called_once_with(PayTransaction(20))

    @patch('stregsystem.models.Member.fulfill')
    def test_order_execute_single_no_remaining(self, fulfill):
        self.product.sale_set.create(price=100, member=self.member)
        self.product.start_date = datetime.date(year=2017, month=1, day=1)
        self.product.quantity = 1
        order = Order(self.member, self.room)

        item = OrderItem(self.product, order, 1)
        order.items.add(item)

        with self.assertRaises(NoMoreInventoryError):
            order.execute()

        fulfill.was_not_called()

    @patch('stregsystem.models.Member.fulfill')
    def test_order_execute_multi_some_remaining(self, fulfill):
        self.product.sale_set.create(price=100, member=self.member)
        self.product.start_date = datetime.date(year=2017, month=1, day=1)
        self.product.quantity = 2
        order = Order(self.member, self.room)

        item = OrderItem(self.product, order, 2)
        order.items.add(item)

        with self.assertRaises(NoMoreInventoryError):
            order.execute()

        fulfill.was_not_called()

    @patch('stregsystem.models.Member.can_fulfill')
    def test_order_execute_no_money(self, can_fulfill):
        can_fulfill.return_value = False
        balance_before = self.member.balance
        order = Order(self.member, self.room)

        item = OrderItem(self.product, order, 2)
        order.items.add(item)

        with self.assertRaises(StregForbudError):
            order.execute()

        balance_after = self.member.balance
        self.assertEqual(balance_before, balance_after)


class PaymentTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(username="jon", balance=100)

    @patch("stregsystem.models.Member.make_payment")
    def test_payment_save_not_saved(self, make_payment):
        payment = Payment(member=self.member, amount=100)

        payment.save()

        make_payment.assert_called_once_with(100)

    @patch("stregsystem.models.Member.make_payment")
    def test_payment_save_already_saved(self, make_payment):
        payment = Payment(member=self.member, amount=100)
        payment.save()
        make_payment.reset_mock()

        payment.save()

        make_payment.assert_not_called()

    @patch("stregsystem.models.Member.make_payment")
    def test_payment_delete_already_saved(self, make_payment):
        payment = Payment(member=self.member, amount=100)
        payment.save()
        make_payment.reset_mock()

        payment.delete()

        make_payment.assert_called_once_with(-100)

    @patch("stregsystem.models.Member.make_payment")
    def test_payment_delete_not_saved(self, make_payment):
        payment = Payment(member=self.member, amount=100)

        with self.assertRaises(ValueError):
            payment.delete()


class ProductTests(TestCase):
    def setUp(self):
        self.jeff = Member.objects.create(
            username="Jeff",
        )

    def test_is_active_active(self):
        product = Product.objects.create(
            active=True,
            price=100,
        )

        self.assertTrue(product.is_active())

    def test_is_active_active_not_expired(self):
        product = Product.objects.create(
            active=True, price=100, deactivate_date=(timezone.now() + datetime.timedelta(hours=1))
        )

        self.assertTrue(product.is_active())

    def test_is_active_active_expired(self):
        product = Product.objects.create(
            active=True, price=100, deactivate_date=(timezone.now() - datetime.timedelta(hours=1))
        )

        self.assertFalse(product.is_active())

    def test_is_active_active_out_of_stock(self):
        product = Product.objects.create(
            active=True, price=100, quantity=1, start_date=datetime.date(year=2017, month=1, day=1)
        )
        product.sale_set.create(price=100, member=self.jeff)

        self.assertFalse(product.is_active())

    def test_is_active_active_in_stock(self):
        product = Product.objects.create(
            active=True, price=100, quantity=2, start_date=datetime.date(year=2017, month=1, day=1)
        )
        product.sale_set.create(price=100, member=self.jeff)

        self.assertTrue(product.is_active())

    def test_is_active_deactive(self):
        product = Product.objects.create(
            active=False,
            price=100,
        )

        self.assertFalse(product.is_active())

    def test_is_active_deactive_expired(self):
        product = Product.objects.create(
            active=False, price=100, deactivate_date=(timezone.now() - datetime.timedelta(hours=1))
        )

        self.assertFalse(product.is_active())

    def test_is_active_deactive_out_of_stock(self):
        product = Product.objects.create(
            active=False, price=100, quantity=1, start_date=datetime.date(year=2017, month=12, day=1)
        )
        product.sale_set.create(price=100, member=self.jeff)

        self.assertFalse(product.is_active())

    def test_is_active_deactive_in_stock(self):
        product = Product.objects.create(
            active=False, price=100, quantity=2, start_date=datetime.date(year=2017, month=12, day=1)
        )
        product.sale_set.create(price=100, member=self.jeff)

        self.assertFalse(product.is_active())


class ProductNoteTest(TestCase):
    fixtures = ["initial_data"]

    def test_appearing(self):
        # Make working product note
        test_product = Product.objects.all().first()
        self.test_product_note = ProductNote(
            text="TEST-NOTE",
            start_date=datetime.date.today(),
            end_date=datetime.date.today(),
        )
        self.test_product_note.save()
        self.test_product_note.products.add(test_product)
        # Make secondary product note, for same product
        self.secondary_test_product_note = ProductNote(
            text="SECONDARY-TEST-NOTE",
            start_date=datetime.date.today(),
            end_date=datetime.date.today(),
        )
        self.secondary_test_product_note.save()
        self.secondary_test_product_note.products.add(test_product)

        # Get the menu
        response = self.client.post(reverse('menu_index', args=(1,)))

        # Test that the note is in the menu
        self.assertContains(response, "TEST-NOTE")
        self.assertContains(response, "SECONDARY-TEST-NOTE")

    def test_chosen_color(self):
        # Make working product note
        test_product = Product.objects.all().first()
        test_product.active = False

        self.test_product_note = ProductNote(
            text="COLORED-NOTE",
            start_date=datetime.date.today(),
            end_date=datetime.date.today(),
            background_color="yellow",
        )
        self.test_product_note.save()
        self.test_product_note.products.add(test_product)

        # Get the menu
        response = self.client.post(reverse('menu_index', args=(1,)))

        self.assertContains(
            response,
            "<span class=\"note-box\" style=\"background-color: yellow; color: black\">COLORED-NOTE</span>",
            html=True,
        )

    def test_incorrect_dates(self):
        # Make expired product note
        test_product = Product.objects.all().first()
        self.test_product_note = ProductNote(
            text="EXPIRED-NOTE",
            start_date=datetime.date.today() - datetime.timedelta(days=1),
            end_date=datetime.date.today() - datetime.timedelta(days=1),
        )
        self.test_product_note.save()
        self.test_product_note.products.add(test_product)
        # Make product note that is not yet active
        self.test_product_note = ProductNote(
            text="FUTURE-NOTE",
            start_date=datetime.date.today() + datetime.timedelta(days=1),
            end_date=datetime.date.today() + datetime.timedelta(days=1),
        )
        self.test_product_note.save()
        self.test_product_note.products.add(test_product)

        # Get the menu
        response = self.client.post(reverse('menu_index', args=(1,)))

        # Test that the note is in the menu
        self.assertNotContains(response, "EXPIRED-NOTE")
        self.assertNotContains(response, "FUTURE-NOTE")

    def test_inactive(self):
        # Make inactive product note
        test_product = Product.objects.all().first()
        self.test_product_note = ProductNote(
            text="INACTIVE-NOTE",
            active=False,
            start_date=datetime.date.today(),
            end_date=datetime.date.today(),
        )
        self.test_product_note.save()
        self.test_product_note.products.add(test_product)

        # Get the menu
        response = self.client.post(reverse('menu_index', args=(1,)))

        # Test that the inactive note doesn't show up
        self.assertNotContains(response, "INACTIVE-NOTE")


class SaleTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(username="jon", balance=100)
        self.product = Product.objects.create(
            name="beer",
            price=1.0,
            active=True,
        )

    def test_sale_save_not_saved(self):
        sale = Sale(member=self.member, product=self.product, price=100)

        sale.save()

        self.assertIsNotNone(sale.id)

    def test_sale_save_already_saved(self):
        sale = Sale(member=self.member, product=self.product, price=100)
        sale.save()

        with self.assertRaises(RuntimeError):
            sale.save()

    def test_sale_delete_not_saved(self):
        sale = Sale(member=self.member, product=self.product, price=100)

        with self.assertRaises(RuntimeError):
            sale.delete()

    def test_sale_delete_already_saved(self):
        sale = Sale(member=self.member, product=self.product, price=100)
        sale.save()

        sale.delete()

        self.assertIsNone(sale.id)


class MemberTests(TestCase):
    def test_fulfill_pay_transaction(self):
        member = Member(balance=100)
        transaction = PayTransaction(10)
        member.fulfill(transaction)

        self.assertEqual(member.balance, 90)

    def test_fulfill_pay_transaction_no_money(self):
        member = Member(balance=2)
        transaction = PayTransaction(10)
        with self.assertRaises(StregForbudError) as c:
            member.fulfill(transaction)

        self.assertTrue(c.exception)
        self.assertEqual(member.balance, 2)

    def test_fulfill_pay_transaction_rollback(self):
        member = Member(balance=2)
        transaction = PayTransaction(10)
        member.rollback(transaction)

        self.assertEqual(member.balance, 12)

    def test_fulfill_check_transaction_has_money(self):
        member = Member(balance=10)
        transaction = PayTransaction(10)

        has_money = member.can_fulfill(transaction)

        self.assertTrue(has_money)

    def test_fulfill_check_transaction_no_money(self):
        member = Member(balance=2)
        transaction = PayTransaction(10)

        has_money = member.can_fulfill(transaction)

        self.assertFalse(has_money)

    def test_make_payment_positive(self):
        member = Member(balance=100)

        member.make_payment(10)

        self.assertEqual(member.balance, 110)

    def test_make_payment_negative(self):
        member = Member(balance=100)

        member.make_payment(-10)

        self.assertEqual(member.balance, 90)

    def test_promille_no_drinks(self):
        user = Member.objects.create(username="test", gender='M')
        non_alcoholic = Product.objects.create(name="mælk", price=1.0, active=True)

        user.sale_set.create(product=non_alcoholic, member=user, price=non_alcoholic.price)

        self.assertEqual(0.0, user.calculate_alcohol_promille())

    def test_promille_with_alcohol_male(self):
        user = Member.objects.create(username="test", gender='M')

        # (330 ml * 4.6%) = 15.18
        alcoholic_drink = Product.objects.create(name="øl", price=2.0, alcohol_content_ml=15.18, active=True)

        user.sale_set.create(product=alcoholic_drink, price=alcoholic_drink.price)

        self.assertAlmostEqual(0.21, user.calculate_alcohol_promille(), places=2)

    def test_promille_with_alcohol_female(self):
        user = Member.objects.create(username="test", gender='F')

        # (330 ml * 4.6%) = 15.18
        alcoholic_drink = Product.objects.create(name="øl", price=2.0, alcohol_content_ml=15.18, active=True)

        user.sale_set.create(product=alcoholic_drink, price=alcoholic_drink.price)

        self.assertAlmostEqual(0.25, user.calculate_alcohol_promille(), places=2)

    def test_promille_staggered_male(self):
        user = Member.objects.create(username="test", gender='M')

        # (330 ml * 4.6%) = 15.18
        alcoholic_drink = Product.objects.create(name="øl", price=2.0, alcohol_content_ml=15.18, active=True)

        with freeze_time(timezone.datetime(year=2000, month=1, day=1, hour=0, minute=0)) as ft:
            for i in range(5):
                ft.tick(delta=datetime.timedelta(minutes=10))
                user.sale_set.create(product=alcoholic_drink, price=alcoholic_drink.price)

        # The last drink was at 2000/01/01 00:50:00

        with freeze_time(timezone.datetime(year=2000, month=1, day=1, hour=0, minute=50)) as ft:
            self.assertAlmostEqual(0.97, user.calculate_alcohol_promille(), places=2)

    def test_promille_staggered_female(self):
        user = Member.objects.create(username="test", gender='F')

        # (330 ml * 4.6%) = 15.18
        alcoholic_drink = Product.objects.create(name="øl", price=2.0, alcohol_content_ml=15.18, active=True)

        with freeze_time(timezone.datetime(year=2000, month=1, day=1, hour=0, minute=0)) as ft:
            for i in range(5):
                ft.tick(delta=datetime.timedelta(minutes=10))
                user.sale_set.create(product=alcoholic_drink, price=alcoholic_drink.price)

        # The last drink was at 2000/01/01 00:50:00

        with freeze_time(timezone.datetime(year=2000, month=1, day=1, hour=0, minute=50)) as ft:
            self.assertAlmostEqual(1.15, user.calculate_alcohol_promille(), places=2)

    def test_send_userdata(self):
        user = Member.objects.create()
        room = Room.objects.create()

        t = timezone.datetime.fromtimestamp(0)

        stregsystem_views.send_userdata(None, room.id, user.id)

        self.assertNotEqual(data_sent[user.id], t)


class BallmerPeakTests(TestCase):
    def test_close_to_maximum(self):
        bac = 1.337 + 0.049

        is_balmer_peaking, minutes, seconds = ballmer_peak(bac)

        self.assertTrue(is_balmer_peaking)
        self.assertEqual(minutes, 39)
        self.assertEqual(seconds, 35)

    def test_close_to_minimum(self):
        bac = 1.337 - 0.049

        is_balmer_peaking, minutes, seconds = ballmer_peak(bac)

        self.assertTrue(is_balmer_peaking)
        self.assertEqual(minutes, 0)
        self.assertEqual(seconds, 24)

    def test_over_peaking(self):
        bac = 1.337 + 0.1

        is_balmer_peaking, minutes, seconds = ballmer_peak(bac)

        self.assertFalse(is_balmer_peaking)
        self.assertEqual(minutes, 20)
        self.assertEqual(seconds, 0)

    def test_under_peaking(self):
        bac = 1.337 - 0.1

        is_balmer_peaking, _, _ = ballmer_peak(bac)

        self.assertFalse(is_balmer_peaking)


class MemberModelFormTests(TestCase):
    def setUp(self):
        jeff = Member.objects.create(username="jeff", firstname="jeff", lastname="jefferson", gender="M")

    def test_cant_create_duplicate_username(self):
        jeff = Member(username="jeff", firstname="jeffrey", lastname="jefferson", gender="M")
        form = MemberForm(model_to_dict(jeff))
        self.assertFalse(form.is_valid())

    def test_cant_create_duplicate_username_in_other_case(self):
        jeff = Member(username="JeFf", firstname="jeffrey", lastname="jefferson", gender="M")
        form = MemberForm(model_to_dict(jeff))
        self.assertFalse(form.is_valid())

    def test_can_create_non_duplicate_username(self):
        not_jeff = Member(username="not_jeff", firstname="jeff", lastname="jefferson", gender="M")
        form = MemberForm(model_to_dict(not_jeff))
        self.assertTrue(form.is_valid())


class MemberAdminTests(TestCase):
    def setUp(self):
        password = "very_secure"
        super_user = User.objects.create_superuser('superuser', 'test@example.com', password)

        self.jeff = Member.objects.create(pk=1, username="jeff", firstname="jeff", lastname="jefferson", gender="M")

        self.jeff2 = Member.objects.create(pk=2, username="jeffrey", firstname="jeff", lastname="jefferson", gender="M")

    def test_creates_warning_for_duplicate_usernames(self):
        self.client.login(username="superuser", password="very_secure")
        self.jeff2.username = "jeff"
        response = self.client.post(
            reverse('admin:stregsystem_member_change', kwargs={'object_id': 2}), model_to_dict(self.jeff2), follow=False
        )

        messages = list(get_messages(response.wsgi_request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(2, len(messages))
        self.assertEqual(str(messages[0]), "Det brugernavn var allerede optaget")
        self.assertEqual("jeff", Member.objects.filter(pk=2).get().username)

    def test_no_warning_unique_usernames(self):
        self.client.login(username="superuser", password="very_secure")
        self.jeff2.username = "mr_jefferson"
        response = self.client.post(
            reverse('admin:stregsystem_member_change', kwargs={'object_id': 2}), model_to_dict(self.jeff2), follow=False
        )

        messages = list(get_messages(response.wsgi_request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(1, len(messages))
        self.assertEqual("mr_jefferson", Member.objects.filter(pk=2).get().username)


class ProductActivatedListFilterTests(TestCase):
    def setUp(self):
        jeff = Member.objects.create(username="jeff")
        Product.objects.create(name="active_dec_none", price=1.0, active=True, deactivate_date=None)
        Product.objects.create(
            name="active_dec_future",
            price=1.0,
            active=True,
            deactivate_date=(timezone.now() + datetime.timedelta(hours=1)),
        )
        Product.objects.create(
            name="active_dec_past",
            price=1.0,
            active=True,
            deactivate_date=(timezone.now() - datetime.timedelta(hours=1)),
        )

        Product.objects.create(name="deactivated_dec_none", price=1.0, active=False, deactivate_date=None)
        Product.objects.create(
            name="deactivated_dec_future",
            price=1.0,
            active=False,
            deactivate_date=(timezone.now() + datetime.timedelta(hours=1)),
        )
        Product.objects.create(
            name="deactivated_dec_past",
            price=1.0,
            active=False,
            deactivate_date=(timezone.now() - datetime.timedelta(hours=1)),
        )
        p = Product.objects.create(
            name="active_none_left",
            price=1.0,
            active=True,
            start_date=datetime.date(year=2017, month=1, day=1),
            quantity=2,
        )
        p.sale_set.create(price=100, member=jeff)
        p.sale_set.create(price=102, member=jeff)
        p = Product.objects.create(
            name="active_some_left",
            price=1.0,
            active=True,
            start_date=datetime.date(year=2017, month=1, day=1),
            quantity=2,
        )
        p.sale_set.create(price=100, member=jeff)

    def test_active_trivial(self):
        fy = admin.ProductActivatedListFilter(None, {'activated': 'Yes'}, Product, ProductAdmin)
        qy = list(fy.queryset(None, Product.objects.all()))
        fn = admin.ProductActivatedListFilter(None, {'activated': 'No'}, Product, ProductAdmin)
        qn = list(fn.queryset(None, Product.objects.all()))

        self.assertIn(Product.objects.get(name="active_dec_none"), qy)
        self.assertNotIn(Product.objects.get(name="active_dec_none"), qn)

    def test_active_deac_future(self):
        fy = admin.ProductActivatedListFilter(None, {'activated': 'Yes'}, Product, ProductAdmin)
        qy = list(fy.queryset(None, Product.objects.all()))
        fn = admin.ProductActivatedListFilter(None, {'activated': 'No'}, Product, ProductAdmin)
        qn = list(fn.queryset(None, Product.objects.all()))

        self.assertIn(Product.objects.get(name="active_dec_future"), qy)
        self.assertNotIn(Product.objects.get(name="active_dec_future"), qn)

    def test_active_deac_past(self):
        fy = admin.ProductActivatedListFilter(None, {'activated': 'Yes'}, Product, ProductAdmin)
        qy = list(fy.queryset(None, Product.objects.all()))
        fn = admin.ProductActivatedListFilter(None, {'activated': 'No'}, Product, ProductAdmin)
        qn = list(fn.queryset(None, Product.objects.all()))

        self.assertNotIn(Product.objects.get(name="active_dec_past"), qy)
        self.assertIn(Product.objects.get(name="active_dec_past"), qn)

    def test_inactive_trivial(self):
        fy = admin.ProductActivatedListFilter(None, {'activated': 'Yes'}, Product, ProductAdmin)
        qy = list(fy.queryset(None, Product.objects.all()))
        fn = admin.ProductActivatedListFilter(None, {'activated': 'No'}, Product, ProductAdmin)
        qn = list(fn.queryset(None, Product.objects.all()))

        self.assertNotIn(Product.objects.get(name="deactivated_dec_none"), qy)
        self.assertIn(Product.objects.get(name="deactivated_dec_none"), qn)

    def test_inactive_deac_future(self):
        fy = admin.ProductActivatedListFilter(None, {'activated': 'Yes'}, Product, ProductAdmin)
        qy = list(fy.queryset(None, Product.objects.all()))
        fn = admin.ProductActivatedListFilter(None, {'activated': 'No'}, Product, ProductAdmin)
        qn = list(fn.queryset(None, Product.objects.all()))

        self.assertNotIn(Product.objects.get(name="deactivated_dec_future"), qy)
        self.assertIn(Product.objects.get(name="deactivated_dec_future"), qn)

    def test_inactive_deac_past(self):
        fy = admin.ProductActivatedListFilter(None, {'activated': 'Yes'}, Product, ProductAdmin)
        qy = list(fy.queryset(None, Product.objects.all()))
        fn = admin.ProductActivatedListFilter(None, {'activated': 'No'}, Product, ProductAdmin)
        qn = list(fn.queryset(None, Product.objects.all()))

        self.assertNotIn(Product.objects.get(name="deactivated_dec_past"), qy)
        self.assertIn(Product.objects.get(name="deactivated_dec_past"), qn)

    def test_active_none_left(self):
        fy = admin.ProductActivatedListFilter(None, {'activated': 'Yes'}, Product, ProductAdmin)
        qy = list(fy.queryset(None, Product.objects.all()))
        fn = admin.ProductActivatedListFilter(None, {'activated': 'No'}, Product, ProductAdmin)
        qn = list(fn.queryset(None, Product.objects.all()))

        self.assertNotIn(Product.objects.get(name="active_none_left"), qy)
        self.assertIn(Product.objects.get(name="active_none_left"), qn)

    def test_active_some_left(self):
        fy = admin.ProductActivatedListFilter(None, {'activated': 'Yes'}, Product, ProductAdmin)
        qy = list(fy.queryset(None, Product.objects.all()))
        fn = admin.ProductActivatedListFilter(None, {'activated': 'No'}, Product, ProductAdmin)
        qn = list(fn.queryset(None, Product.objects.all()))

        self.assertIn(Product.objects.get(name="active_some_left"), qy)
        self.assertNotIn(Product.objects.get(name="active_some_left"), qn)


class ProductRoomFilterTests(TestCase):
    fixtures = ["test_room_products"]

    def test_general_room_dont_get_special_items(self):
        numberOfSpecialItems = 2
        response = self.client.get(reverse('menu_index', args=(1,)))
        product_pairs = response.context['product_note_pair_list']
        specialProduct = Product.objects.get(pk=3)

        any(self.assertFalse(specialProduct == pair.product) for pair in product_pairs)
        self.assertEqual(len(product_pairs), len(Product.objects.all()) - numberOfSpecialItems)

    def test_special_room_get_special_items(self):
        response = self.client.get(reverse('menu_index', args=(2,)))
        product_pairs = response.context['product_note_pair_list']
        specialProduct = Product.objects.get(pk=3)

        self.assertTrue(any(specialProduct == pair.product) for pair in product_pairs)
        self.assertEqual(len(product_pairs), len(Product.objects.all()))


class CategoryAdminTests(TestCase):
    fixtures = ["test_category"]

    def test_category_counter_empty(self):
        testCategory = Category.objects.get(pk=1)
        admin = CategoryAdmin(Category, testCategory)
        self.assertEqual(0, admin.items_in_category(testCategory))

    def test_category_counter_single_product(self):
        testCategory = Category.objects.get(pk=2)
        admin = CategoryAdmin(Category, testCategory)
        self.assertEqual(1, admin.items_in_category(testCategory))


class QuickbuyParserTests(TestCase):
    def setUp(self):
        self.test_username = 'test'

    def test_username_only(self):
        buy_string = self.test_username

        username, products = parser.parse(buy_string)

        self.assertEqual(self.test_username, username)
        self.assertEqual(len(products), 0)

    def test_single_buy(self):
        product_ids = [42]
        buy_string = self.test_username + ' 42'

        username, products = parser.parse(buy_string)

        self.assertEqual(username, self.test_username)
        self.assertEqual(len(products), 1)
        assertCountEqual(self, product_ids, products)

    def test_multi_buy(self):
        product_ids = [42, 1337]
        buy_string = self.test_username + " 42 1337"

        username, products = parser.parse(buy_string)

        self.assertEqual(username, self.test_username)
        self.assertEqual(len(products), len(product_ids))
        assertCountEqual(self, product_ids, products)

    def test_multi_buy_repeated(self):
        product_ids = [42, 42]
        buy_string = self.test_username + " 42 42"

        username, products = parser.parse(buy_string)

        self.assertEqual(username, self.test_username)
        self.assertEqual(len(products), len(product_ids))
        assertCountEqual(self, product_ids, products)

    def test_multi_buy_quantifier(self):
        product_ids = [42, 42, 1337, 1337, 1337]
        buy_string = self.test_username + " 42:2 1337:3"

        username, products = parser.parse(buy_string)

        self.assertEqual(username, self.test_username)
        self.assertEqual(len(products), len(product_ids))
        assertCountEqual(self, product_ids, products)

    def test_zero_quantifier(self):
        buy_string = self.test_username + " 42:0"

        username, products = parser.parse(buy_string)

        self.assertEqual(username, self.test_username)
        self.assertEqual(len(products), 0)

    def test_negative_quantifier(self):
        buy_string = self.test_username + ' 42:-1 1337:3'
        with self.assertRaises(parser.QuickBuyError):
            parser.parse(buy_string)

    def test_missing_quantifier(self):
        buy_string = self.test_username + ' 42: 1337:3'
        with self.assertRaises(parser.QuickBuyError):
            parser.parse(buy_string)

    def test_invalid_quantifier(self):
        buy_string = self.test_username + ' 42:a 1337:3'
        with self.assertRaises(parser.QuickBuyError):
            parser.parse(buy_string)

    def test_invalid_productId(self):
        buy_string = self.test_username + ' a:2 1337:3'
        with self.assertRaises(parser.QuickBuyError):
            parser.parse(buy_string)


class RazziaTests(TestCase):
    def setUp(self):
        self.flan = Product.objects.create(name="FLan", price=1.0, active=True)
        self.flanmad = Product.objects.create(name="FLan mad", price=2.0, active=True)
        self.notflan = Product.objects.create(name="Ikke Flan", price=2.0, active=True)

        self.alan = Member.objects.create(username="tester", firstname="Alan", lastname="Alansen")
        self.bob = Member.objects.create(username="bob", firstname="bob", lastname="bob")

        with freeze_time('2017-02-02'):
            Sale.objects.create(member=self.alan, product=self.flan, price=1.0)

        with freeze_time('2017-02-15'):
            Sale.objects.create(member=self.alan, product=self.flan, price=1.0)

        with freeze_time('2017-02-07'):
            Sale.objects.create(member=self.alan, product=self.flanmad, price=1.0)

        with freeze_time('2017-02-05'):
            Sale.objects.create(member=self.alan, product=self.notflan, price=1.0)

    def test_sales_to_user_in_period(self):
        res = views._sales_to_user_in_period(
            self.alan.username,
            timezone.datetime(2017, 2, 1, 0, 0, tzinfo=pytz.UTC),
            timezone.datetime(2017, 2, 17, 0, 0, tzinfo=pytz.UTC),
            [self.flan.id, self.flanmad.id],
            {self.flan.name: 0, self.flanmad.name: 0},
        )

        self.assertEqual(2, res[self.flan.name])
        self.assertEqual(1, res[self.flanmad.name])

    def test_sales_to_user_no_results_out_of_period(self):
        res = views._sales_to_user_in_period(
            self.bob.username,
            timezone.datetime(2017, 2, 1, 0, 0, tzinfo=pytz.UTC),
            timezone.datetime(2017, 2, 17, 0, 0, tzinfo=pytz.UTC),
            [self.flan.id, self.flanmad.id],
            {self.flan.name: 0, self.flanmad.name: 0},
        )

        self.assertEqual(0, res[self.flan.name])
        self.assertEqual(0, res[self.flanmad.name])


class MobilePaymentTests(TestCase):
    def setUp(self):
        self.fixture_path = "stregsystem/fixtures/mobilepay-sales-testdata-fixture.csv"

        # setup admin
        self.super_user = User.objects.create_superuser('superuser', 'test@example.com', "hunter2")
        self.autopayment_user = User.objects.create_superuser('autopayment', 'foo@bar.com', 'hunter2')

        # Create members, directly mirrors fixture in 'stregsystem/fixtures/testdata-mobilepay.json'
        self.members = {
            'jdoe': {
                'username': 'jdoe',
                'firstname': 'John',
                'lastname': 'Doe',
                'email': 'jdoe@nsa.gov',
                'balance': 42000,
            },
            'marx': {
                'username': 'marx',
                'firstname': 'Karl',
                'lastname': 'Marx',
                'email': 'marx@nsa.gov',
                'balance': 6900,
            },
            'tables': {
                'username': 'tables',
                'firstname': 'Bobby',
                'lastname': 'Tables',
                'email': 'tables@nsa.gov',
                'balance': 12500,
            },
            'mlarsen': {
                'username': 'mlarsen',
                'firstname': 'Martin',
                'lastname': 'Larsen',
                'email': 'mlarsen@nsa.gov',
                'balance': 10000,
            },
            'tester': {
                'username': 'tester',
                'firstname': 'Test',
                'lastname': 'Testsen',
                'email': 'tables@nsa.gov',
                'balance': 50000,
            },
        }
        for member in self.members:
            Member.objects.create(
                username=self.members[member]['username'],
                firstname=self.members[member]['firstname'],
                lastname=self.members[member]['lastname'],
                email=self.members[member]['email'],
                balance=self.members[member]['balance'],
            ).save()

        from stregsystem.utils import parse_csv_and_create_mobile_payments

        with open(self.fixture_path, "r") as csv_file:
            parse_csv_and_create_mobile_payments(csv_file.readlines())

        # fixture for mobilepaytool form submission
        self.fixture_form_data_no_change = [
            {
                "amount": 6969,
                "comment": "mlarsen indbetalt",
                "id": MobilePayment.objects.get(transaction_id="156E027485173228"),
                "member": None,
                "status": MobilePayment.UNSET,
                "timestamp": parse_datetime("2019-11-29T13:51:08.8574424+01:00"),
            },
            {
                "amount": 50000,
                "comment": "tables eksdee",
                "id": MobilePayment.objects.get(transaction_id="232E027452733666"),
                "member": None,
                "status": MobilePayment.UNSET,
                "timestamp": parse_datetime("2019-11-28T17:40:55.7194894+01:00"),
            },
            {
                "amount": 50000,
                "comment": "tables eksdee",
                "id": MobilePayment.objects.get(transaction_id="232E027452733676"),
                "member": None,
                "status": MobilePayment.UNSET,
                "timestamp": parse_datetime("2019-11-28T17:40:55.7194894+01:00"),
            },
            {
                "amount": 20000,
                "comment": "marx",
                "id": MobilePayment.objects.get(transaction_id="241E027449465355"),
                "member": "+ marx: Karl Marx | kmarx@nsa.gov (69.00)",
                "status": MobilePayment.UNSET,
                "timestamp": parse_datetime("2019-11-28T15:30:58.3578294+01:00"),
            },
            {
                "amount": 15000,
                "comment": "jdoe",
                "id": MobilePayment.objects.get(transaction_id="016E027417049990"),
                "member": "+ jdoe: John Doe | jdoe@nsa.gov (420.00)",
                "status": MobilePayment.UNSET,
                "timestamp": parse_datetime("2019-11-27T12:15:38.5290119+01:00"),
            },
            {
                "amount": 20000,
                "comment": "tester",
                "id": MobilePayment.objects.get(transaction_id="207E027395896809"),
                "member": "+ tester: Test Testsen | plznospam@fklub.dk (133660.37)",
                "status": MobilePayment.UNSET,
                "timestamp": parse_datetime("2019-11-26T12:54:37.5216501+01:00"),
            },
        ]
        # fixture where only marx is approved
        self.fixture_form_data_marx_approved = deepcopy(self.fixture_form_data_no_change)
        self.fixture_form_data_marx_approved[3]['status'] = MobilePayment.APPROVED

        # fixture where both marx and jdoe is approved
        self.fixture_form_data_marx_jdoe_approved = deepcopy(self.fixture_form_data_marx_approved)
        self.fixture_form_data_marx_jdoe_approved[4]['status'] = MobilePayment.APPROVED

    def test_csv_parsing(self):
        self.assertEqual(MobilePayment.objects.count(), 6)

        # two bobby-payments in test data
        self.assertEqual(MobilePayment.objects.filter(comment__icontains="tables").count(), 2)

        payment_timestamp = MobilePayment.objects.get(transaction_id="156E027485173228").timestamp
        # manually accounting for UTC+1 timezone at time of transaction
        real_timestamp = datetime.datetime(2019, 11, 29, 12, 51, 8, tzinfo=pytz.UTC)
        self.assertLess((payment_timestamp - real_timestamp).seconds, 1)

    def test_multiple_csv_submission(self):
        # csv fixture contains six payments, ensure that setup created those
        self.assertEqual(MobilePayment.objects.count(), 6)

        # do import once again on same csv fixture
        from stregsystem.utils import parse_csv_and_create_mobile_payments

        with open(self.fixture_path, "r") as csv_file:
            parse_csv_and_create_mobile_payments(csv_file.readlines())

        # mobilepayment count should remain unchanged
        self.assertEqual(MobilePayment.objects.count(), 6)

    def test_member_exact_matching(self):
        for matched_member in MobilePayment.objects.filter(member__isnull=False):
            self.assertEqual(matched_member.member, Member.objects.get(pk=matched_member.member.pk))

    def test_approved_payment_balance(self):
        # member balance unchanged
        self.assertEqual(Member.objects.get(username__exact="jdoe").balance, self.members["jdoe"]['balance'])

        # submit mobile payment
        self.client.login(username="superuser", password="hunter2")

        mobile_payment = MobilePayment.objects.get(transaction_id__exact="016E027417049990")
        mobile_payment.status = MobilePayment.APPROVED
        mobile_payment.save()

        MobilePayment.submit_all_processed_mobile_payments(self.super_user)

        self.assertEqual(
            Member.objects.get(username__exact="jdoe").balance, self.members["jdoe"]['balance'] + mobile_payment.amount
        )

    def test_ignored_payment_balance(self):
        # member balance unchanged
        self.assertEqual(Member.objects.get(username__exact="tester").balance, self.members["tester"]['balance'])

        # submit mobile payment
        self.client.login(username="superuser", password="hunter2")

        mobile_payment = MobilePayment.objects.get(transaction_id__exact="207E027395896809")
        mobile_payment.status = MobilePayment.IGNORED
        mobile_payment.save()

        MobilePayment.submit_all_processed_mobile_payments(self.super_user)

        self.assertEqual(Member.objects.get(username__exact="tester").balance, self.members["tester"]['balance'])

    def test_batch_submission_balance(self):
        # member balance unchanged
        for member in self.members:
            self.assertEqual(
                Member.objects.get(username__exact=self.members[member]['username']).balance,
                self.members[member]['balance'],
            )

        # submit mobile payment
        self.client.login(username="superuser", password="hunter2")

        # approve all exact matches
        for matched_mobile_payment in MobilePayment.objects.filter(member__isnull=False):
            matched_mobile_payment.status = MobilePayment.APPROVED
            matched_mobile_payment.save()

        # manually approve bobby
        bobby_tables_mobile_payment1 = MobilePayment.objects.get(transaction_id__exact="232E027452733666")
        bobby_tables_mobile_payment1.member = Member.objects.get(username__exact="tables")
        bobby_tables_mobile_payment1.status = MobilePayment.APPROVED
        bobby_tables_mobile_payment1.save()

        MobilePayment.submit_all_processed_mobile_payments(self.super_user)

        # assert that each member who has an approved mobile payment has their balance updated by the amount given
        for approved_mobile_payment in MobilePayment.objects.filter(status__exact=MobilePayment.APPROVED):
            member = Member.objects.get(pk=approved_mobile_payment.member.pk)
            self.assertEqual(member.balance, approved_mobile_payment.amount + self.members[member.username]['balance'])

    def test_member_balance_on_delete_approved_mobilepayment(self):
        # member balance unchanged before submission
        self.assertEqual(Member.objects.get(username__exact="jdoe").balance, self.members["jdoe"]['balance'])

        # submit mobile payment
        self.client.login(username="superuser", password="hunter2")

        mobile_payment = MobilePayment.objects.get(transaction_id__exact="016E027417049990")
        mobile_payment.status = MobilePayment.APPROVED
        mobile_payment.save()

        MobilePayment.submit_all_processed_mobile_payments(self.super_user)

        # ensure new balance is mobilepayment amount
        self.assertEqual(
            Member.objects.get(username__exact="jdoe").balance, self.members["jdoe"]['balance'] + mobile_payment.amount
        )

        # delete payment
        MobilePayment.objects.get(transaction_id__exact="016E027417049990").delete()

        # ensure member balance is original amount, as deletion of mobilepayment should revert change
        self.assertEqual(Member.objects.get(username__exact="jdoe").balance, self.members["jdoe"]['balance'])

    def test_member_balance_on_delete_ignored_mobilepayment(self):
        # member balance unchanged before submission
        self.assertEqual(Member.objects.get(username__exact="jdoe").balance, self.members["jdoe"]['balance'])

        # submit mobile payment
        self.client.login(username="superuser", password="hunter2")

        mobile_payment = MobilePayment.objects.get(transaction_id__exact="016E027417049990")
        mobile_payment.status = MobilePayment.IGNORED
        mobile_payment.save()

        MobilePayment.submit_all_processed_mobile_payments(self.super_user)

        # ensure balance is still initial amount
        self.assertEqual(Member.objects.get(username__exact="jdoe").balance, self.members["jdoe"]['balance'])

        # delete payment
        mobile_payment.delete()

        # ensure member balance is original amount, as deletion of mobilepayment should revert change
        self.assertEqual(Member.objects.get(username__exact="jdoe").balance, self.members["jdoe"]['balance'])

    def test_member_balance_on_delete_unset_mobilepayment(self):
        # member balance unchanged before submission
        self.assertEqual(Member.objects.get(username__exact="jdoe").balance, self.members["jdoe"]['balance'])

        # submit mobile payments
        self.client.login(username="superuser", password="hunter2")
        MobilePayment.submit_all_processed_mobile_payments(self.super_user)

        # ensure balance is still initial amount
        self.assertEqual(Member.objects.get(username__exact="jdoe").balance, self.members["jdoe"]['balance'])

        # delete payment
        MobilePayment.objects.get(transaction_id__exact="016E027417049990").delete()

        # ensure member balance is original amount, as deletion of mobilepayment should revert change
        self.assertEqual(Member.objects.get(username__exact="jdoe").balance, self.members["jdoe"]['balance'])

    def test_exact_guess(self):
        self.assertEqual(Member.objects.get(username__exact="marx"), mobile_payment_exact_match_member("marx"))

    def test_emoji_strip(self):
        self.assertEqual(strip_emoji("Tilmeld Lichi 😎"), "Tilmeld Lichi")

    def test_emoji_strip_electric_boogaloo(self):
        # Laurits bør få næse for at fremprovokere dette case
        self.assertEqual(strip_emoji("♂️Laurits♂️"), "Laurits")

    def test_emoji_retain_nordic(self):
        self.assertEqual(strip_emoji("æøåäëö"), "æøåäëö")

    def test_emoji_retain(self):
        self.assertEqual(strip_emoji("Tilmeld Lichi"), "Tilmeld Lichi")

    def test_allowlist(self):
        self.assertEqual(
            strip_emoji("a-zA-Z0-9äåæéëöø!#$%&()*+,\-_./:;<=>?@\^`\]{|}~£§¶Ø"),
            "a-zA-Z0-9äåæéëöø!#$%&()*+,\-_./:;<=>?@\^`\]{|}~£§¶Ø",
        )

    def test_esoteric_chars(self):
        # Weirsøe bør få næse for at fremprovokere dette case
        self.assertEqual(strip_emoji("tilmeld ἂ"), "tilmeld")

    def test_underscore_char(self):
        self.assertEqual(strip_emoji("_"), "_")

    def test_mobilepaytool_race_no_error(self):
        # do autopayment
        MobilePayment.approve_member_filled_mobile_payments()
        MobilePayment.submit_all_processed_mobile_payments(self.autopayment_user)
        # assert that no changes have been made, also that MobilePaytoolException is not thrown
        self.assertEqual(MobilePayment.process_submitted(self.fixture_form_data_no_change, self.super_user), 0)

    def test_mobilepaytool_race_error_marx(self):
        # do autopayment
        MobilePayment.approve_member_filled_mobile_payments()
        MobilePayment.submit_all_processed_mobile_payments(self.autopayment_user)

        # assert exception is thrown and values in exception are as expected
        with self.assertRaises(PaymentToolException):
            try:
                MobilePayment.process_submitted(self.fixture_form_data_marx_approved, self.super_user)
            except PaymentToolException as e:
                self.assertEqual(e.inconsistent_mbpayments_count, 1)
                self.assertEqual(e.inconsistent_transaction_ids, ["241E027449465355"])
                raise e

    def test_mobilepaytool_race_error_marx_jdoe(self):
        # do autopayment
        MobilePayment.approve_member_filled_mobile_payments()
        MobilePayment.submit_all_processed_mobile_payments(self.autopayment_user)

        # assert exception is thrown and values in exception are as expected
        with self.assertRaises(PaymentToolException):
            try:
                MobilePayment.process_submitted(self.fixture_form_data_marx_jdoe_approved, self.super_user)
            except PaymentToolException as e:
                self.assertEqual(e.inconsistent_mbpayments_count, 2)
                self.assertEqual(e.inconsistent_transaction_ids, ["241E027449465355", "016E027417049990"])
                raise e


class AutoPaymentTests(TestCase):
    def setUp(self):
        self.autopayment_user = User.objects.create_superuser('autopayment', 'foo@bar.com', 'hunter2')
        self.member = Member.objects.create(
            username='tester', firstname='Test', lastname='Testsen', email='tables@nsa.gov', balance=178
        )

    def test_ignore_lt_50_20(self):
        comment = 'tester'
        MobilePayment.objects.create(
            amount=2000,
            comment=comment,
            timestamp=parse_datetime("2022-05-16T13:51:08.8574424+01:00"),
            transaction_id='156E027485173228',
            member=mobile_payment_exact_match_member(comment),
        )

        MobilePayment.approve_member_filled_mobile_payments()
        MobilePayment.submit_all_processed_mobile_payments(self.autopayment_user)

        unset = MobilePayment.objects.get(transaction_id='156E027485173228')
        self.assertEqual(unset.status, MobilePayment.UNSET)

    def test_ignore_lt_50_49(self):
        comment = 'tester'
        MobilePayment.objects.create(
            amount=4999,
            comment=comment,
            timestamp=parse_datetime("2022-05-16T13:51:08.8574424+01:00"),
            transaction_id='156E027485173228',
            member=mobile_payment_exact_match_member(comment),
        )

        MobilePayment.approve_member_filled_mobile_payments()
        MobilePayment.submit_all_processed_mobile_payments(self.autopayment_user)

        unset = MobilePayment.objects.get(transaction_id='156E027485173228')
        self.assertEqual(unset.status, MobilePayment.UNSET)

    def test_approve_gte_50(self):
        comment = 'tester'
        MobilePayment.objects.create(
            amount=5000,
            comment=comment,
            timestamp=parse_datetime("2022-05-16T13:51:09.8574424+01:00"),
            transaction_id='156E027485173229',
            member=mobile_payment_exact_match_member(comment),
        )

        MobilePayment.approve_member_filled_mobile_payments()
        MobilePayment.submit_all_processed_mobile_payments(self.autopayment_user)

        approved = MobilePayment.objects.get(transaction_id='156E027485173229')
        self.assertEqual(approved.status, MobilePayment.APPROVED)

    def test_approve_gte_50_big(self):
        comment = 'tester'
        MobilePayment.objects.create(
            amount=500000,
            comment=comment,
            timestamp=parse_datetime("2022-05-16T13:51:09.8574424+01:00"),
            transaction_id='156E027485173229',
            member=mobile_payment_exact_match_member(comment),
        )

        MobilePayment.approve_member_filled_mobile_payments()
        MobilePayment.submit_all_processed_mobile_payments(self.autopayment_user)

        approved = MobilePayment.objects.get(transaction_id='156E027485173229')
        self.assertEqual(approved.status, MobilePayment.APPROVED)

    @mock.patch('stregsystem.models.send_payment_mail', autospec=True)
    def test_payment_mail_normal_mobile_payment(self, mock_mail_method: MagicMock):
        from stregsystem.management.commands.autopayment import Command

        mock_mail_method.return_value = None

        MobilePayment.objects.create(amount=5000, timestamp=timezone.now(), member=self.member)

        cmd = Command()
        cmd.handle()

        mock_mail_method.assert_called_once()


class CaffeineCalculatorTest(TestCase):
    def test_default_caffeine_is_zero(self):
        product = Product.objects.create(name="some product", price=420.0, active=True)

        self.assertEqual(product.caffeine_content_mg, 0)

    def test_calculate_is_zero_if_no_caffeine_is_consumed(self):
        user = Member.objects.create(username="test", gender='M', balance=100)
        NOTcoffee = Product.objects.create(name="koffeinfri kaffe", price=2.0, caffeine_content_mg=0, active=True)

        user.sale_set.create(product=NOTcoffee, price=NOTcoffee.price)

        self.assertEqual(0, user.calculate_caffeine_in_body())

    def test_calculate_is_non_zero_if_some_caffeine_is_consumed(self):
        user = Member.objects.create(username="test", gender='M', balance=100)
        coffee = Product.objects.create(
            name="koffeinholdig kaffe", price=2.0, caffeine_content_mg=CAFFEINE_IN_COFFEE, active=True
        )

        user.sale_set.create(product=coffee, price=coffee.price)

        self.assertAlmostEqual(CAFFEINE_IN_COFFEE, user.calculate_caffeine_in_body(), delta=0.001)

    def test_caffeine_1_hour(self):
        with freeze_time() as frozen_datetime:
            user = Member.objects.create(username="test", gender='M', balance=100)
            coffee = Product.objects.create(
                name="Kaffe☕☕☕", price=1, caffeine_content_mg=CAFFEINE_IN_COFFEE, active=True
            )

            user.sale_set.create(product=coffee, price=coffee.price)

            frozen_datetime.tick(delta=datetime.timedelta(hours=1))

            self.assertAlmostEqual(
                CAFFEINE_IN_COFFEE * (1 - CAFFEINE_DEGRADATION_PR_HOUR) ** 1,
                user.calculate_caffeine_in_body(),
                delta=0.001,
            )  # There could be a rounding error

    def test_caffeine_degradation_for_1_to_10_hours(self):
        for hours in range(1, 10):
            with freeze_time() as frozen_datetime:
                user = Member.objects.create(username="test", gender='M', balance=100)
                coffee = Product.objects.create(
                    name="Kaffe☕☕☕", price=1, caffeine_content_mg=CAFFEINE_IN_COFFEE, active=True
                )

                user.sale_set.create(product=coffee, price=coffee.price)

                frozen_datetime.tick(delta=datetime.timedelta(hours=hours))
                self.assertAlmostEqual(
                    CAFFEINE_IN_COFFEE * (1 - CAFFEINE_DEGRADATION_PR_HOUR) ** hours,
                    user.calculate_caffeine_in_body(),
                    delta=0.001,
                )

    def test_caffeine_half_time_twice_with_two_cups(self):
        with freeze_time() as frozen_datetime:
            user = Member.objects.create(username="test", gender='M', balance=100)
            coffee = Product.objects.create(
                name="Kaffe☕☕☕", price=1, caffeine_content_mg=CAFFEINE_IN_COFFEE, active=True
            )

            user.sale_set.create(product=coffee, price=coffee.price)
            frozen_datetime.tick(delta=datetime.timedelta(hours=5))

            self.assertAlmostEqual(
                CAFFEINE_IN_COFFEE * (1 - CAFFEINE_DEGRADATION_PR_HOUR) ** 5,
                user.calculate_caffeine_in_body(),
                delta=0.001,
            )

            user.sale_set.create(product=coffee, price=coffee.price)
            frozen_datetime.tick(delta=datetime.timedelta(hours=5))

            # expected value is compound interest of 1 cup in mg for 5h, then rest + 1 cup in mg for additional 5h
            self.assertAlmostEqual(
                ((CAFFEINE_IN_COFFEE * (1 - CAFFEINE_DEGRADATION_PR_HOUR) ** 5) + CAFFEINE_IN_COFFEE)
                * (1 - CAFFEINE_DEGRADATION_PR_HOUR) ** 5,
                user.calculate_caffeine_in_body(),
                delta=0.001,
            )

    def test_multiple_caffeine_intake_at_odd_times(self):
        tick_one = datetime.timedelta(hours=2, minutes=24)
        tick_two = datetime.timedelta(hours=1, minutes=13, seconds=16)

        with freeze_time() as frozen_datetime:
            user = Member.objects.create(username="test", gender='M', balance=100)
            coffee = Product.objects.create(
                name="Kaffe☕☕☕", price=1, caffeine_content_mg=CAFFEINE_IN_COFFEE, active=True
            )

            # do sale and tick_one
            user.sale_set.create(product=coffee, price=coffee.price)
            frozen_datetime.tick(delta=tick_one)

            # calc and assert degradation of 1 cup during tick_one
            expected_caffeine_in_body = float(
                CAFFEINE_IN_COFFEE * (1 - CAFFEINE_DEGRADATION_PR_HOUR) ** (tick_one / datetime.timedelta(hours=1)),
            )

            self.assertAlmostEqual(
                expected_caffeine_in_body,
                user.calculate_caffeine_in_body(),
                delta=0.001,
            )

            # do another sale and tick_two
            user.sale_set.create(product=coffee, price=coffee.price)
            frozen_datetime.tick(delta=tick_two)

            # first add consumed caffeine from second sale, then degrade, since no time passes after last consume
            expected_caffeine_in_body += CAFFEINE_IN_COFFEE

            expected_caffeine_in_body = float(
                expected_caffeine_in_body
                * (1 - CAFFEINE_DEGRADATION_PR_HOUR) ** (tick_two / datetime.timedelta(hours=1)),
            )

            self.assertAlmostEqual(
                expected_caffeine_in_body,
                user.calculate_caffeine_in_body(),
                delta=0.001,
            )

    def test_caffeine_str_is_correct_length(self):
        user = Member.objects.create(username="test", gender='F', balance=100)
        coffee = Product.objects.create(
            name="Kaffe☕☕☕", price=1, caffeine_content_mg=CAFFEINE_IN_COFFEE, active=True
        )

        # do five sales of coffee and assert that emoji renderer returns same amount of emoji
        sales = 5
        with freeze_time() as _:
            for _ in range(0, sales):
                user.sale_set.create(product=coffee, price=coffee.price)

            # keep assert within scope of freeze_time to ensure degradation is not applied
            self.assertEqual("☕" * sales, caffeine_emoji_render(user.calculate_caffeine_in_body()))

    def test_rich_guy_is_leading_coffee_addict(self):
        coffee_addict = Member.objects.create(username="Anders", gender="M", balance=100)
        average_developer = Member.objects.create(username="my-guy", gender="M", balance=50)
        coffee_category = Category.objects.create(name="Caffeine☕☕☕", pk=6)
        coffee_category.save()
        coffee = Product.objects.create(name="Kaffe☕☕☕", price=1, caffeine_content_mg=70, active=True)
        coffee.save()
        coffee.categories.add(coffee_category)

        [coffee_addict.sale_set.create(product=coffee, price=coffee.price) for _ in range(5)]
        [average_developer.sale_set.create(product=coffee, price=coffee.price) for _ in range(2)]

        self.assertTrue(coffee_addict.is_leading_coffee_addict())
        self.assertFalse(average_developer.is_leading_coffee_addict())

    def test_if_sunday_is_in_week(self):
        coffee_addict = Member.objects.create(username="Ida", gender="F", balance=100)
        average_developer = Member.objects.create(username="my-gal", gender="F", balance=50)
        coffee_category = Category.objects.create(name="Caffeine☕☕☕", pk=6)
        coffee_category.save()
        coffee = Product.objects.create(
            name="Kaffe☕☕☕", price=1, caffeine_content_mg=CAFFEINE_IN_COFFEE, active=True
        )
        # matches coffee id in production. Will be implemented with categories later, when production have a coffee
        # category
        coffee.save()
        coffee.categories.add(coffee_category)

        with freeze_time(timezone.datetime(year=2021, day=29, month=11, hour=8)) as monday:
            coffee_addict.sale_set.create(product=coffee, price=coffee.price)

        with freeze_time(timezone.datetime(year=2021, day=5, month=12, hour=8)) as sunday:
            coffee_addict.sale_set.create(product=coffee, price=coffee.price)
            average_developer.sale_set.create(product=coffee, price=coffee.price)

            self.assertTrue(coffee_addict.is_leading_coffee_addict())
            self.assertFalse(average_developer.is_leading_coffee_addict())


class SignupTest(TestCase):
    def setUp(self):
        self.autopayment_user = User.objects.create_superuser('autopayment', 'foo@bar.com', 'hunter2')
        self.mock_mobile_payment = MobilePayment(timestamp=timezone.now(), amount=20000, transaction_id="1")

    def test_signup_request_creation(self):
        user_info = {
            'username': 'john',
            'firstname': 'John',
            'lastname': 'doe',
            'email': 'johndoe@example.com',
            'gender': 'M',
        }

        self.client.post(reverse('signup'), user_info)

        # assert that the member was created and that the due payment status is correctly set
        member = Member.objects.get(username=user_info['username'])
        self.assertIsNotNone(member)
        self.assertFalse(member.signup_due_paid)

        # assert that the PendingSignup for the new user was created
        signup_request = PendingSignup.objects.get(member=member)
        self.assertIsNotNone(signup_request)

    def test_signup_completion(self):
        member = Member.objects.create(username='john', signup_due_paid=False)
        signup = PendingSignup.objects.create(member=member, status=ApprovalModel.APPROVED)
        signup.complete(self.mock_mobile_payment)

        # Assert that the signup due payment status has been updated correctly
        member = Member.objects.get(pk=member.pk)
        self.assertTrue(member.signup_due_paid)

        # Assert that the PendingSignup instance has been deleted
        with self.assertRaises(PendingSignup.DoesNotExist):
            _ = PendingSignup.objects.get(member=member)

    def test_excess_payment_balance(self):
        member = Member.objects.create(username='john', signup_due_paid=False)
        signup = PendingSignup.objects.create(member=member, due=-50000)
        signup.complete(self.mock_mobile_payment)

        # Assert that excess payment was added to the account balance
        member = Member.objects.get(pk=member.pk)
        self.assertEqual(member.balance, 50000)

    def test_autopayment_command_single_payment(self):
        from stregsystem.management.commands.autopayment import Command

        member = Member.objects.create(username='john', signup_due_paid=False)
        PendingSignup.objects.create(member=member, status=ApprovalModel.APPROVED)

        self.mock_mobile_payment.member = member
        self.mock_mobile_payment.save()

        cmd = Command()
        cmd.handle()

        # Assert that the signup due payment status has been updated correctly
        member = Member.objects.get(pk=member.pk)
        self.assertTrue(member.signup_due_paid)

        # Assert that the payment status has been set correctly
        payment = MobilePayment.objects.get(pk=self.mock_mobile_payment.pk)
        self.assertEqual(payment.status, MobilePayment.APPROVED)

        # Assert that the PendingSignup instance has been deleted
        with self.assertRaises(PendingSignup.DoesNotExist):
            _ = PendingSignup.objects.get(member=member)

    def test_autopayment_command_split_payment(self):
        """
        tests that signup payments that are split over more than one
        mobile payment work properly
        """
        from stregsystem.management.commands.autopayment import Command

        member = Member.objects.create(username='john', signup_due_paid=False)
        PendingSignup.objects.create(
            member=member, due=self.mock_mobile_payment.amount * 2, status=ApprovalModel.APPROVED
        )

        self.mock_mobile_payment.member = member
        self.mock_mobile_payment.save()

        second_payment = MobilePayment(timestamp=timezone.now(), amount=20000, transaction_id="2", member=member)

        cmd = Command()
        cmd.handle()

        # Assert that the signup due payment status remains false
        member = Member.objects.get(pk=member.pk)
        self.assertFalse(member.signup_due_paid)

        # Assert that the payment status has been set correctly
        payment = MobilePayment.objects.get(pk=self.mock_mobile_payment.pk)
        self.assertEqual(payment.status, MobilePayment.APPROVED)

        # Register second payment and rerun command
        second_payment.save()
        cmd.handle()

        # Assert that the signup due payment status has been updated correctly
        member = Member.objects.get(pk=member.pk)
        self.assertTrue(member.signup_due_paid)

        # Assert that the payment status has been set correctly
        payment = MobilePayment.objects.get(pk=second_payment.pk)
        self.assertEqual(payment.status, MobilePayment.APPROVED)

        # Assert that the PendingSignup instance has been deleted
        with self.assertRaises(PendingSignup.DoesNotExist):
            _ = PendingSignup.objects.get(member=member)

    def test_autopayment_command_double_payment_unset_approval(self):
        """
        tests that signup payments that are split over more than one
        mobile payment work properly, while not approved.
        """
        from stregsystem.management.commands.autopayment import Command

        member = Member.objects.create(username='john', signup_due_paid=False)
        PendingSignup.objects.create(member=member, due=self.mock_mobile_payment.amount, status=ApprovalModel.UNSET)

        self.mock_mobile_payment.member = member
        self.mock_mobile_payment.save()

        second_payment = MobilePayment(timestamp=timezone.now(), amount=20000, transaction_id="2", member=member)

        cmd = Command()
        cmd.handle()

        # Assert that the signup due payment status is true
        member = Member.objects.get(pk=member.pk)
        self.assertTrue(member.signup_due_paid)

        # Assert that the payment status has been set correctly
        payment = MobilePayment.objects.get(pk=self.mock_mobile_payment.pk)
        self.assertEqual(payment.status, MobilePayment.APPROVED)

        # Register second payment and rerun command
        second_payment.save()
        cmd.handle()

        # Assert that the payment status has been set correctly
        payment = MobilePayment.objects.get(pk=second_payment.pk)
        self.assertEqual(payment.status, MobilePayment.APPROVED)

        # Assert that the payment has been added to the member account
        member = Member.objects.get(pk=member.pk)
        self.assertEqual(member.balance, second_payment.amount)

        # Assert that the PendingSignup instance has not been deleted (since it isn't approved)
        _ = PendingSignup.objects.get(member=member)

    def test_signup_approval_after_due(self):
        """
        Tests that a signup is successful, when approved after due is paid.
        """
        member = Member.objects.create(username='john', signup_due_paid=True)
        signup = PendingSignup.objects.create(member=member, status=ApprovalModel.UNSET)

        # Approve signup after due has been paid.
        signup.status = ApprovalModel.APPROVED
        signup.save()

        # Assert that the PendingSignup instance has been deleted
        with self.assertRaises(PendingSignup.DoesNotExist):
            _ = PendingSignup.objects.get(member=member)

    @mock.patch('stregsystem.models.send_payment_mail', autospec=True)
    @mock.patch('stregsystem.models.send_welcome_mail', autospec=True)
    def test_only_welcome_mail_excess_balance(self, mock_welcome_mail: MagicMock, mock_payment_mail: MagicMock):
        """
        Test that only welcome mail is sent, when a member is signed up with excess payment.
        """
        from stregsystem.management.commands.autopayment import Command

        mock_welcome_mail.return_value = None
        mock_payment_mail.return_value = None

        member = Member.objects.create(username='john', signup_due_paid=False)
        PendingSignup.objects.create(
            member=member, due=self.mock_mobile_payment.amount / 2, status=ApprovalModel.APPROVED
        )

        self.mock_mobile_payment.member = member
        self.mock_mobile_payment.save()

        cmd = Command()
        cmd.handle()

        mock_payment_mail.assert_not_called()
        mock_welcome_mail.assert_called_once()

    @mock.patch('stregsystem.models.send_payment_mail', autospec=True)
    @mock.patch('stregsystem.models.send_welcome_mail', autospec=True)
    def test_only_welcome_mail_no_excess_balance(self, mock_welcome_mail: MagicMock, mock_payment_mail: MagicMock):
        """
        Test that only welcome mail is sent, when a member is signed up.
        """
        from stregsystem.management.commands.autopayment import Command

        mock_welcome_mail.return_value = None
        mock_payment_mail.return_value = None

        member = Member.objects.create(username='john', signup_due_paid=False)
        PendingSignup.objects.create(member=member, due=self.mock_mobile_payment.amount, status=ApprovalModel.APPROVED)

        self.mock_mobile_payment.member = member
        self.mock_mobile_payment.save()

        cmd = Command()
        cmd.handle()

        mock_payment_mail.assert_not_called()
        mock_welcome_mail.assert_called_once()


class MailTests(TestCase):
    def setUp(self):
        pass

    @mock.patch('stregsystem.models.send_welcome_mail', autospec=True)
    def test_welcome_mail_manual_create_member(self, mock_mail_method: MagicMock):
        mock_mail_method.return_value = None

        member = Member.objects.create(username="jeff", email="test@example.com")

        mock_mail_method.assert_called_once()

    @mock.patch('stregsystem.models.send_welcome_mail', autospec=True)
    def test_no_welcome_mail_no_paid_approved(self, mock_mail_method: MagicMock):
        mock_mail_method.return_value = None

        member = Member.objects.create(username="jeff", email="test@example.com", signup_due_paid=False)
        signup_request = PendingSignup(member=member, due=200 * 100)
        signup_request.save()

        signup_request.approve()

        mock_mail_method.assert_not_called()

    @mock.patch('stregsystem.models.send_welcome_mail', autospec=True)
    def test_no_welcome_mail_paid_unset(self, mock_mail_method: MagicMock):
        mock_mail_method.return_value = None

        # Create member with no due paid
        member = Member.objects.create(username="jeff", email="test@example.com", signup_due_paid=False)
        signup_request = PendingSignup(member=member, due=200)
        signup_request.save()

        # Add payment but still not approved
        payment = MobilePayment.objects.create(amount=200, timestamp=timezone.now())
        signup_request.complete(payment)
        mock_mail_method.assert_not_called()

    @mock.patch('stregsystem.models.send_welcome_mail', autospec=True)
    def test_welcome_mail_paid_approved(self, mock_mail_method: MagicMock):
        mock_mail_method.return_value = None

        # Create member with no due paid, then attach pendingsignup, and then say they've paid.
        member = Member.objects.create(username="jeff", email="test@example.com", signup_due_paid=False)
        signup_request = PendingSignup(member=member, due=200)
        signup_request.save()

        payment = MobilePayment.objects.create(amount=200, timestamp=timezone.now())
        signup_request.complete(payment)

        signup_request.approve()
        mock_mail_method.assert_called_once()
