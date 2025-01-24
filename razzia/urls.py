from django.urls import re_path
from . import views

urlpatterns = [
    re_path(r'^admin/razzia/(?P<razzia_id>\d+)/$', views.razzia, name="razzia_view"),
    re_path(r'^admin/razzia/(?P<razzia_id>\d+)/members$', views.razzia_members, name="razzia_members_view"),
    re_path(r'^admin/razzia/(?P<razzia_id>\d+)/settings$', views.razzia_settings, name="razzia_settings_view"),
    re_path(r'^admin/razzia/$', views.razzia_menu, name="razzia_menu"),
    re_path(r'^admin/razzia/new$', views.new_razzia, name="razzia_new"),
]
