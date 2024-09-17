import datetime
import unittest

from django.test import TestCase

from fkult.models import Season, Movie, Event

TEST_IMDB_IDS = [
    # pulp fiction
    'tt0110912',
    # dune 2021
    'tt1160419',
    # the dark knight rises
    'tt1345836',
    # the matrix
    'tt0133093',
    # the lion king
    'tt0110357',
    # the godfather
    'tt0068646',
    # the godfather part 2
    'tt0071562',
    # the dark knight
    'tt0468569',
    # batman
    'tt0096895',
    # goodfellas
    'tt0099685',
    # interstellar
    'tt0816692',
    # the martian
    'tt3659388',
    # the terminator
    'tt0088247',
    # the terminator 2
    'tt0103064',
    # the bourne identity
    'tt0258463',
    # brave
    'tt1217209',
    # mr robot
    'tt0499549',
]


class SeasonTests(TestCase):
    def test_overlap(self):
        Season.objects.create(start_date=datetime.date(2021, 2, 1), end_date=datetime.date(2021, 6, 30))
        with self.assertRaises(RuntimeError, msg='Season overlaps with existing season'):
            Season.objects.create(start_date=datetime.date(2021, 2, 2), end_date=datetime.date(2021, 6, 29))

    @staticmethod
    def test_no_overlap():
        Season.objects.create(start_date=datetime.date(2021, 2, 1), end_date=datetime.date(2021, 6, 30))
        Season.objects.create(start_date=datetime.date(2021, 7, 1), end_date=datetime.date(2021, 9, 30))


class IntegrationTest(TestCase):
    def setUp(self) -> None:
        [Movie.get_or_create_from_id(imdb_id) for imdb_id in TEST_IMDB_IDS]

    def test_movie_count(self):
        self.assertEqual(Movie.objects.count(), 17)

    def test_duplicate_movie(self):
        a = Movie.get_or_create_from_id('tt0110912')
        b = Movie.get_or_create_from_id('tt0110912')
        self.assertEqual(a, b)

    @unittest.skip("Doesn't catch raised error")
    def test_failed_tmdb_lookup(self):
        with self.assertRaises(RuntimeError):
            Movie.get_or_create_from_id('tt9999999')

    @unittest.skip("Doesn't test to completion")
    def test_create_event(self):
        movie = Movie.get_or_create_from_id('tt0110912')
        event = Event.objects.create(theme='test')
        event.movies.add(movie)
        self.assertIn(movie, event.movies.all())
        self.assertEqual(event.event_date, datetime.date(2021, 2, 1))
        self.assertEqual(
            event.season,
            Season.objects.get(start_date__lte=datetime.date(2021, 2, 1), end_date__gte=datetime.date(2021, 2, 1)),
        )

        # test that the event is created
        self.assertEqual(event.id, 1)
        self.assertEqual(event.movie.id, 1)
