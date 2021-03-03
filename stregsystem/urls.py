from django.urls import include, re_path

from . import views
from django.shortcuts import redirect

"""stregsystem URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/ref/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  re_path(r'^$', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  re_path(r'^$', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.conf.urls import url, include
    2. Add a URL to urlpatterns:  re_path(r'^blog/', include('blog.urls'))
"""
urlpatterns = [
    re_path(r'^$', views.roomindex, name="index"),
    re_path(r'^admin/batch/$', views.batch_payment, name="batch"),
    re_path(r'^admin/mobilepaytool/$', views.mobilepaytool, name="mobilepaytool"),
    re_path(r'^admin/totalsales/$', views.total_sales_monthly, name="total_monthly_sales"),
    re_path(r'^(?P<room_id>\d+)/$', views.index, name="menu_index"),
    re_path(r'^(?P<room_id>\d+)/sale/$', views.sale, name="quickbuy"),
    re_path(r'^(?P<room_id>\d+)/sale/(?P<member_id>\d+)/$', views.menu_sale, name="menu"),
    re_path(r'^(?P<room_id>\d+)/sale/\d+/\d+/$', lambda request, room_id: redirect('menu_index', room_id=room_id), name="menu_sale"),
    re_path(r'^(?P<room_id>\d+)/user/(?P<member_id>\d+)/$', views.menu_userinfo, name="userinfo"),
    re_path(r'^(?P<room_id>\d+)/user/(?P<member_id>\d+)/pay$', views.menu_userpay, name="userpay"),
    re_path(r'^api/member/payment/qr$', views.qr_payment, name="payment_qr"),
]
