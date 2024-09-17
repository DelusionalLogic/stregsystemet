import json
import datetime
from pprint import pprint

from tmdbv3api import TMDb, Movie as TMDbMovie, Search
from typing import List

from fkult.models import Movie, Event
from treo.settings import cfg

tmdb = TMDb()
tmdb.api_key = cfg.get("tmdb", "API_KEY")
tmdb.language = 'en'
tmdb_movie = TMDbMovie()


class JSONFkultEvent:
    date: datetime.datetime
    movies: list
    f_kult_user: str
    proposer: str
    theme: str

    def __init__(
        self,
        year: int,
        date: str,
        movies: list,
        suggester_fklub_id: str = None,
        suggester_name: str = None,
        theme: str = None,
    ):
        self.__set_date(year, date)
        self.movies = movies
        self.f_kult_user = suggester_fklub_id
        self.proposfer = suggester_name
        self.theme = theme

    def __set_date(self, year, date):
        self.date = datetime.datetime.strptime(f"{year}, {date}", '%Y, %B %d')

    def test_movies(self):
        return [{"n": m, "is": not not movie.search(m)} for m in self.movies]

    def get_json(self):
        return json.dumps(
            {
                "date": self.date.strftime('%Y/%m/%d'),
                "name": self.proposer,
                "f_kult_user": self.f_kult_user,
                "movies": self.movies,
                "theme": self.theme,
            }
        )


def create_movie_from_json_fkult_event(events: List[JSONFkultEvent]):
    for event in events:
        movies = []
        for movie in event.movies:
            s = tmdb_movie.search(movie)
            if s:
                # take first hit from tmdb and create movie
                movies.append(Movie.get_or_create_from_id(s[0].id))

        if movies:
            # create event
            e = Event.objects.create(
                theme=event.theme if event.theme else "N/A",
                event_date=event.date,
                proposer=event.proposer if event.proposer else None,
            )
            [e.movies.add(m) for m in movies]


def import_fkult_from_json(json_file):
    res_obj = {}

    obj = json.loads(json_file.read())
    res: List[JSONFkultEvent] = []
    for key, value in obj.items():
        year = key
        for season, events in value.items():
            spring = True if season == "spring" else False
            for date, info in events.items():
                res.append(JSONFkultEvent(year=year, date=date, movies=info["movies"], theme=info["theme"]))


"""        value: dict
        res_obj[key] = {
            "spring": [
                {"date": d, "suggester": None, "theme": None, "movies": m} for d, m in value.get("spring").items()
            ],
            "fall": [{"date": d, "suggester": None, "theme": None, "movies": m} for d, m in value.get("fall").items()],
        }

    all_data = []
    for year, spring_or_fall in obj.items():
        # springpprint(event)
        for date, movies in spring_or_fall.get("spring").items():
            all_data.append(JSONFkultEvent(year, date, movies))
        for date, movies in spring_or_fall.get("fall").items():
            all_data.append(JSONFkultEvent(year, date, movies))

    create_movie_from_json_fkult_event(all_data)
"""