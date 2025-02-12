from django.shortcuts import redirect
from django.urls import re_path

from . import views

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
    re_path(r'^admin/payment_tool/$', views.payment_tool, name="payment_tool"),
    re_path(r'^admin/signup_tool/$', views.signup_tool, name="signup_tool"),
    re_path(r'^signup/$', views.signup, name="signup"),
    re_path(r'^signup/(?P<signup_id>\d+)$', views.signup_status, name="signup_status"),
    re_path(r'^(?P<room_id>\d+)/$', views.index, name="menu_index"),
    re_path(r'^(?P<room_id>\d+)/sale/$', views.sale, name="quickbuy"),
    re_path(r'^(?P<room_id>\d+)/sale/(?P<member_id>\d+)/$', views.menu_sale, name="menu"),
    re_path(r'^(?P<room_id>\d+)/sale/\d+/\d+/$', lambda request, room_id: redirect('menu_index', room_id=room_id), name="menu_sale"),
    re_path(r'^(?P<room_id>\d+)/user/(?P<member_id>\d+)/$', views.menu_userinfo, name="userinfo"),
    re_path(r'^(?P<room_id>\d+)/user/(?P<member_id>\d+)/pay$', views.menu_userpay, name="userpay"),
    re_path(r'^(?P<room_id>\d+)/user/(?P<member_id>\d+)/rank$', views.menu_userrank, name="userrank"),
    re_path(r'^(?P<room_id>\d+)/send_csv_mail/(?P<member_id>\d+)/$', views.send_userdata, name="send_userdata"),
    re_path(r'^api/member/payment/qr$', views.get_payment_qr, name="api_payment_qr"),
    re_path(r'^api/member/active$', views.get_member_active, name="api_member_active"),
    re_path(r'^api/member/sales$', views.get_member_sales, name="api_member_sales"),
    re_path(r'^api/member/get_id$', views.get_member_id, name="api_member_id"),
    re_path(r'^api/member/balance$', views.get_member_balance, name="api_member_balance"),
    re_path(r'^api/member$', views.get_member_info, name="api_member_info"),
    re_path(r'^api/products/named_products$', views.get_named_products, name="api_named_products"),
    re_path(r'^api/products/active_products$', views.get_active_items, name="api_active_products"),
    re_path(r'^api/products/category_mappings$', views.get_product_category_mappings, name="api_product_mappings"),
    re_path(r'^api/sale$', views.api_sale, name="api_sale"),
    re_path(r'^api/signup$', views.post_signup, name="api_signup"),
    re_path(r'^api/signup/status', views.get_signup_status, name="api_signup_status"),
]
