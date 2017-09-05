from django.contrib.admin.views.decorators import staff_member_required

import datetime
import fpformat
import collections

from django.core.cache import caches
from django.db.models import Count
from django.db.models import Q
from django.db.models import Sum
from django.shortcuts import render

from stregsystem.models import Member
from stregsystem.models import Sale
from stregsystem.models import Product

def reports(request):
    return render(request, 'admin/stregsystem/report/index.html', locals())

reports = staff_member_required(reports)

def sales(request):
    if request.method == 'POST':
        return sales_product(request, strings_to_whole(request.POST['products'].split()), request.POST['from_date'], request.POST['to_date'])
    else:
        return sales_product(request, None, None, None)

sales = staff_member_required(sales)

def bread(request):
    if request.method == 'POST':
        return bread_view(request, request.POST['username'])
    else:
        return bread_view(request, None)


def clear_bread_cache(request):
    caches['bread_cache'].clear()
    return bread(request)


bread = staff_member_required(bread)


def bread_view(request, queryname):
    cache = caches['bread_cache']
    if queryname is not None and not cache.get(queryname):
        cache.set(queryname, True, 60*60*24)
        result = list(Member.objects.filter(username__iexact=queryname))
        if len(result) > 0:
            member = result[0]

    return render(request, 'admin/stregsystem/razzia/bread.html', locals())


def ranks(request, year = None):
    if (year):
        return ranks_for_year(request, int(year))
    else:
        return ranks_for_year(request, next_fjule_party_year())

ranks = staff_member_required(ranks)

def sales_product(request, ids, from_time, to_time):
    date_format = '%Y-%m-%d'

    try:
        try:
            from_date_time = datetime.datetime.strptime(from_time, date_format)
        except:
            from_date_time = first_of_month(datetime.datetime.now())
        from_time = from_date_time.strftime(date_format)

        try:
            to_date_time = late(datetime.datetime.strptime(to_time, date_format))
        except:
            to_date_time = datetime.datetime.now()
        to_time = to_date_time.strftime(date_format)
        sales = []
        if ids and len(ids) > 0:
            products = reduce(lambda a, b: a + str(b) + ' ', ids, '')
            query = reduce(lambda x, y: x | y, map(lambda z: Q(id=z), ids))
            query &= Q(sale__timestamp__gt = from_date_time)
            query &= Q(sale__timestamp__lte = to_date_time)
            result = Product.objects.filter(query).annotate(Count('sale'), Sum('sale__price'))

            count = 0
            sum = 0
            for r in result:
                sales.append((r.pk, r.name, r.sale__count, money(r.sale__price__sum)))
                count = count + r.sale__count
                sum = sum + r.sale__price__sum

            sales.append(('', 'TOTAL', count, money(sum)))
    except:
        return render(request, 'admin/stregsystem/report/error_invalidsalefetch.html', locals())
    return render(request, 'admin/stregsystem/report/sales.html', locals())

# renders stats for the year starting at first friday in december (year - 1) to the first friday in december (year)
# both at 10 o'clock
def ranks_for_year(request, year):
    if (year <= 1900 or year > 9999):
        return render(request, 'admin/stregsystem/report/error_ranksnotfound.html', locals())
    milk = [2, 3, 4, 5, 6, 7, 8, 9, 10, 16, 17, 18, 19, 20, 24, 25, 43, 44, 45, 1865 ]
    caffeine = [11, 12, 30, 34, 37, 1787, 1790, 1791, 1795, 1799, 1800, 1803, 1804, 1837, 1864]
    beer = [13, 14, 29, 42, 47, 54, 65, 66, 1773, 1776, 1777, 1779, 1780, 1783, 1793, 1794, 1807, 1808, 1809, 1820, 1822, 1840, 1844, 1846, 1847, 1853, 1855, 1856, 1858, 1859]
    coffee = [32, 35, 36, 39]
    vitamin = [1850, 1851, 1852, 1863]

    FORMAT = '%d/%m/%Y kl. %H:%M'
    last_year = year - 1
    from_time = fjule_party(year - 1)
    to_time = fjule_party(year)
    kr_stat_list = sale_money_rank(from_time, to_time)
    beer_stat_list = sale_product_rank(beer, from_time, to_time)
    caffeine_stat_list = sale_product_rank(caffeine, from_time, to_time)
    milk_stat_list = sale_product_rank(milk, from_time, to_time)
    coffee_stat_list = sale_product_rank(coffee, from_time, to_time)
    vitamin_stat_list = sale_product_rank(vitamin, from_time, to_time)
    from_time_string = from_time.strftime(FORMAT)
    to_time_string = to_time.strftime(FORMAT)
    current_date = datetime.datetime.now()
    is_ongoing = current_date > from_time and current_date <= to_time
    return render(request, 'admin/stregsystem/report/ranks.html', locals())

# gives a list of member objects, with the additional field sale__count, with the number of sales which are in the parameter id
def sale_product_rank(ids, from_time, to_time, rank_limit=10):
    stat_list = Member.objects.filter(sale__timestamp__gt=from_time, sale__timestamp__lte=to_time, sale__product__in=ids).annotate(Count('sale')).order_by('-sale__count', 'username')[:rank_limit]
    return stat_list

# gives a list of member object, with the additional field sale__price__sum__formatted which is the number of money spent in the period given.
def sale_money_rank(from_time, to_time, rank_limit=10):
    stat_list = Member.objects.filter(active=True, sale__timestamp__gt = from_time, sale__timestamp__lte = to_time).annotate(Sum('sale__price')).order_by('-sale__price__sum', 'username')[:rank_limit]
    for member in stat_list:
        member.sale__price__sum__formatted = money(member.sale__price__sum)
    return stat_list

#year of the last fjuleparty
def last_fjule_party_year():
    current_date = datetime.datetime.now()
    fjule_party_this_year = fjule_party(current_date.year)
    if current_date > fjule_party_this_year:
        return current_date.year
    return current_date.year - 1

#year of the next fjuleparty
def next_fjule_party_year():
    current_date = datetime.datetime.now()
    fjule_party_this_year = fjule_party(current_date.year)
    if current_date <= fjule_party_this_year:
        return current_date.year
    return current_date.year + 1

#date of fjuleparty (first friday of december) for the given year at 10 o'clock
def fjule_party(year):
    first_december = datetime.datetime(year, 12, 1, 22)
    days_to_add = (11 - first_december.weekday()) % 7
    return first_december + datetime.timedelta(days = days_to_add)

def money(value):
    if value is None:
        value = 0
    return fpformat.fix(value/100.0,2)

def strings_to_whole(strings):
    def append_if_digit(list, digit):
        if isinstance(digit, unicode) and digit.isdigit():
            list.append(int(digit))
        return list
    if not isinstance(strings, collections.Iterable):
        return []
    return reduce(append_if_digit, strings, [])

def late(date):
    return datetime.datetime(date.year, date.month, date.day, 23, 59, 59)

def first_of_month(date):
    return datetime.datetime(date.year, date.month, 1, 23, 59, 59)
