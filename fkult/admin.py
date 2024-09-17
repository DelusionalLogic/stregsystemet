from django.contrib import admin

from fkult.models import Movie, Event, Season

admin.site.register(Movie)
admin.site.register(Season)


class EventAdmin(admin.ModelAdmin):
    list_display = ('theme', 'event_date', 'proposer', 'votes', 'accepted', 'season')
    valid_lookups = 'theme'


admin.site.register(Event, EventAdmin)
