from django.urls import re_path

from . import views

urlpatterns = [
    re_path(r'^$', views.index, name='index'),
    re_path(r'^suggest$', views.suggest_event, name='suggest'),
    re_path(r'^vote$', views.vote_event, name='vote_event'),
]
