from datetime import datetime, timedelta, timezone
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime
from pathlib import Path

from requests import HTTPError

from stregsystem.models import MobilePayment
import json
import logging
import requests

from stregsystem.utils import mobile_payment_exact_match_member, strip_emoji


class Command(BaseCommand):
    help = 'Imports the latest payments from MobilePay'

    api_endpoint = 'https://api.mobilepay.dk'
    # Saves secret tokens to the file "tokens.json" right next to this file.
    # Important to use a separate file since the tokens can change and is thus not suitable for django settings.
    tokens_file = (Path(__file__).parent / 'tokens.json').as_posix()
    tokens = None

    logger = logging.getLogger(__name__)
    days_back = None

    def add_arguments(self, parser):
        parser.add_argument(
            'days_back',
            nargs='?',
            type=int,
            default=7,
            help="Days back from today to look for MobilePay transactions (max 31 days)",
        )

    def handle(self, *args, **options):
        self.days_back = options['days_back'] if options['days_back'] <= 31 else 7
        self.import_mobilepay_payments()

    def write_debug(self, s):
        self.logger.debug(s)

    def write_info(self, s):
        self.logger.info(s)

    def write_warning(self, s):
        self.logger.warning(s)

    def write_error(self, s):
        self.logger.error(s)

    # Reads the token file from disk
    def read_token_storage(self):
        with open(self.tokens_file, 'r') as json_file:
            self.tokens = json.load(json_file)

    # Saves the token variable to disk
    def update_token_storage(self):
        with open(self.tokens_file, 'w') as json_file:
            json.dump(self.tokens, json_file, indent=2)

    # Fetches a new access token using the refresh token.
    def refresh_access_token(self):
        url = f"{self.api_endpoint}/merchant-authentication-openidconnect/connect/token"

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.tokens['refresh_token'],
            "client_id": self.tokens['zip-client-id'],
            "client_secret": self.tokens['zip-client-secret'],
        }
        response = requests.post(url, data=payload)
        response.raise_for_status()
        json_response = response.json()
        # Calculate when the token expires
        expire_time = datetime.now() + timedelta(seconds=json_response['expires_in'] - 1)
        self.tokens['access_token_timeout'] = expire_time.isoformat(timespec='milliseconds')
        self.tokens['access_token'] = json_response['access_token']
        self.update_token_storage()

    # Format to timestamp format. Source:
    # https://github.com/MobilePayDev/MobilePay-TransactionReporting-API/blob/master/docs/api/types.md#timestamp
    @staticmethod
    def format_datetime(inputdatetime):
        return f"{inputdatetime.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z"

    # Fetches the transactions for a given payment-point (MobilePay phone-number) in a given period (from-to)
    def get_transactions(self):
        url = f"{self.api_endpoint}/transaction-reporting/api/merchant/v1/paymentpoints/{self.tokens['paymentpoint']}/transactions"
        current_time = datetime.now(timezone.utc)
        params = {
            'from': self.format_datetime(current_time - timedelta(days=self.days_back)),
            'to': self.format_datetime(current_time),
        }
        headers = {
            'x-ibm-client-secret': self.tokens['ibm-client-secret'],
            'x-ibm-client-id': self.tokens['ibm-client-id'],
            'authorization': 'Bearer {}'.format(self.tokens['access_token']),
        }
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()['transactions']

    # Client side check if the token has expired.
    def refresh_expired_token(self):
        self.read_token_storage()
        expire_time = parse_datetime(self.tokens['access_token_timeout'])
        if datetime.now() >= expire_time:
            self.refresh_access_token()

    def fetch_transactions(self):
        # Do a client side check if token is good. If not - fetch another token.
        try:
            self.refresh_expired_token()
            assert self.days_back is not None
            return self.get_transactions()
        except HTTPError as e:
            self.write_error(f"Got an HTTP error when trying to fetch transactions: {e.response}")
        except Exception as e:
            self.write_error(f'Got an error when trying to fetch transactions.')
            pass

    def import_mobilepay_payments(self):
        transactions = self.fetch_transactions()
        if transactions is None:
            self.write_info(f'Ran, but no transactions found')
            return

        for transaction in transactions:
            self.import_mobilepay_payment(transaction)

        self.write_info('Successfully ran MobilePayment API import')

    def import_mobilepay_payment(self, transaction):
        if transaction['type'] != 'Payment':
            return

        trans_id = transaction['paymentTransactionId']

        if MobilePayment.objects.filter(transaction_id=trans_id).exists():
            self.write_debug(f'Skipping transaction since it already exists (Transaction ID: {trans_id})')
            return

        currency_code = transaction['currencyCode']
        if currency_code != 'DKK':
            self.write_warning(f'Does ONLY support DKK (Transaction ID: {trans_id}), was {currency_code}')
            return

        # convert to streg-ører
        amount = transaction['amount'] * 100

        comment = strip_emoji(transaction['senderComment'])

        payment_datetime = parse_datetime(transaction['timestamp'])

        MobilePayment.objects.create(
            amount=amount,
            member=mobile_payment_exact_match_member(comment),
            comment=comment,
            timestamp=payment_datetime,
            transaction_id=trans_id,
            status=MobilePayment.UNSET if amount >= 5000 else MobilePayment.LOW_AMOUNT,
        )

        self.write_info(f'Imported transaction id: {trans_id} for amount: {amount}')
