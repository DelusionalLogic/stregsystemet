from django.urls import re_path

from . import views

urlpatterns = [
    re_path(r'^$', views.index, name='index'),
    re_path(r'^suggest$', views.suggest_event, name='suggest'),
    re_path(r'^vote$', views.vote_event, name='vote'),
    re_path(r'^generate$', views.generate_season, name='generate'),
    re_path(r'^import_json$', views.import_json, name='import_json'),
    re_path(r'^lookup$', views.lookup, name='lookup'),
]
