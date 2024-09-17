from pprint import pprint

import requests
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import permission_required
from django.forms import modelformset_factory
from django.http import HttpResponseRedirect
from django.shortcuts import render

from fkult.forms import MovieForm, EventForm, EventVoteForm, GenerateSeasonNumberForm, JsonForm, LookupForm
from fkult.import_json import import_fkult_from_json
from fkult.models import Movie, Event, Season

CURR_SEASON = Season.objects.order_by('-id').first()


def index(request):
    curr_season = CURR_SEASON
    events = Event.objects.filter(season=CURR_SEASON)

    return render(request, "fkult/index.html", locals())


def suggest_event(request):
    movie_formset_factory = modelformset_factory(Movie, form=MovieForm, extra=2, max_num=2)
    movie_formset = movie_formset_factory(queryset=Movie.objects.none())  # this is probably bad form
    event_form = EventForm()

    if request.method == 'POST':
        movie_formset = movie_formset_factory(request.POST)
        event_form = EventForm(request.POST)
        if movie_formset.is_valid():
            # todo check that suggestions have not been accepted within the previous 7 years
            if event_form.is_valid():
                movies = [Movie.get_or_create_from_id(movie['movie_id']) for movie in movie_formset.cleaned_data]

                # create event
                e = Event.objects.create(
                    theme=event_form.cleaned_data['theme'], proposer=event_form.cleaned_data['fember'], accepted=False
                )
                [e.movies.add(m) for m in movies]
                e.save()
                status = ("Submitted", e.__str__())

                # refresh form
                movie_formset = movie_formset_factory(queryset=Movie.objects.none())
                event_form = EventForm()

    return render(request, "fkult/suggest.html", locals())


@staff_member_required()
@permission_required("fkult.admin")  # todo, make fkult permission
def vote_event(request):
    curr_season = CURR_SEASON

    vote_formset_factory = modelformset_factory(Event, form=EventVoteForm, extra=0)
    vote_formset = vote_formset_factory(queryset=Event.objects.filter(season__isnull=True))  # this is probably bad form

    if request.method == 'POST':
        vote_formset = vote_formset_factory(request.POST or None)
        if vote_formset.is_valid():
            vote_formset.save()
            return HttpResponseRedirect('/fkult/generate')

    return render(request, "fkult/vote.html", locals())


@staff_member_required()
@permission_required("fkult.admin")  # todo, make fkult permission
def generate_season(request):
    form = GenerateSeasonNumberForm()

    if request.method == 'POST':
        form = GenerateSeasonNumberForm(request.POST)
        if form.is_valid():
            season, created = Season.create_season(form.cleaned_data['start_date'], form.cleaned_data['end_date'])
            return HttpResponseRedirect('/fkult/')

    return render(request, "fkult/generate.html", locals())


@staff_member_required()
@permission_required("fkult.admin")  # todo, make fkult permission
def import_json(request):
    if request.method == 'POST':
        form = JsonForm(request.POST, request.FILES)
        if form.is_valid():
            res = import_fkult_from_json(form.cleaned_data['json'])
            pprint(res)
    else:
        form = JsonForm()

    return render(request, "fkult/import_json.html", locals())


def lookup(request):
    if request.method == 'POST':
        form = LookupForm(request.POST)
        if form.is_valid():
            # return result
            pass
    else:
        form = LookupForm()

    return render(request, "fkult/lookup.html", locals())
