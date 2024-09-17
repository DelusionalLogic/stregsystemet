from django.conf import settings
from django.urls import include, re_path
from django.conf.urls.static import static
from django.contrib import admin

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
    re_path(r'^', include("stregsystem.urls")),
    re_path(r'^', include("stregreport.urls")),
    re_path(r'^kiosk/', include("kiosk.urls")),
    re_path(r'^fkult/', include("fkult.urls")),
    re_path(r'^admin/', admin.site.urls),
    re_path(r'^select2/', include('django_select2.urls')),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [
        re_path(r'^__debug__/', include(debug_toolbar.urls)),
    ] + urlpatterns
