import datetime

from django import forms
from django.forms import TextInput, HiddenInput

from fkult.models import Movie, Event, Season
from stregsystem.models import Member
from treo.settings import cfg

from django_select2 import forms as s2forms


class EventForm(forms.ModelForm):
    fember = forms.CharField()

    class Meta:
        model = Event
        fields = ["theme"]
        widgets = {"proposer": TextInput}

    def clean_fember(self):
        # checks if proposer username exists and returns it, otherwise raise validation error
        cleaned_proposer = self.cleaned_data['fember']
        try:
            return Member.objects.get(username__iexact=cleaned_proposer)
        except Member.DoesNotExist:
            raise forms.ValidationError(
                f"'{cleaned_proposer}' is not a username, please try again - it's not a case sensitive input"
            )

    # todo override save function - why?


class EventVoteForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ['id', 'theme', 'movies', 'proposer', 'votes']
        widgets = {"proposer": TextInput}

    def __init__(self, *args, **kwargs):
        super(EventVoteForm, self).__init__(*args, **kwargs)
        # Make fields not meant for editing by user readonly (note that this is prevented in template as well)
        if self.instance.id:
            for field in self.fields:
                if field in ['id', 'event_date', 'theme', 'movies', 'proposer', 'accepted', 'season']:
                    self.fields[field].widget.attrs['readonly'] = True

    def clean_id(self):
        instance = getattr(self, 'instance', None)
        if instance and instance.pk:
            return instance.id
        else:
            return self.cleaned_data['id']


class MovieForm(forms.ModelForm):
    movie_id = forms.CharField(label='The IMDB ID of movie', max_length=20)

    class Meta:
        model = Movie
        fields = []

    def clean_movie_id(self):
        cleaned_id = self.cleaned_data['movie_id']
        from tmdbv3api import TMDb, exceptions, Movie as TMDbMovie

        tmdb = TMDb()
        tmdb.api_key = cfg.get("tmdb", "API_KEY")
        tmdb.language = 'en'
        tmdb_movie = TMDbMovie()

        # make TMDB lookup on id, if fail - get mad, otherwise just return same
        try:
            _ = tmdb_movie.details(movie_id=cleaned_id)
        except exceptions.TMDbException:
            raise forms.ValidationError(
                f'"{cleaned_id}" IMDB/TMDb id could not be found. Check your given ID on imdb.com or themoviedb.org'
            )

        return cleaned_id


class GenerateSeasonNumberForm(forms.Form):
    start_date = forms.DateField(initial=datetime.datetime.now() + datetime.timedelta(days=14))
    end_date = forms.DateField(initial=datetime.datetime.now() + datetime.timedelta(days=365 / 2))


class JsonForm(forms.Form):
    json = forms.FileField(label='JSON file', help_text='Upload a JSON file of Fkult movies to import')


class Select2MovieWidget(s2forms.ModelSelect2Widget):
    search_fields = ['title__icontains']
    model = Movie


class LookupForm(forms.ModelForm):
    class Meta:
        model = Movie
        fields = ['title']
        widgets = {'title': Select2MovieWidget}
