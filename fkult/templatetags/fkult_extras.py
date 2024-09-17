from django import template

register = template.Library()


def proposer_format(member):
    from stregsystem.models import Member

    if isinstance(member, Member):
        return f"{member.firstname}, class {member.year}"
    if isinstance(member, int):
        try:
            m = Member.objects.get(id=member)
            return f"{m.firstname}, class of {m.year}"
        except Member.DoesNotExist:
            return f"No member with pk={member}"
    else:
        return "N/A"


def movie_imdb_link(movie):
    from fkult.models import Movie

    if isinstance(movie, Movie):
        return f'<a href="https://www.imdb.com/title/{movie.id}/">{movie.__str__()}</a>'
    else:
        return movie


def movie_imdb_link_list(movie_list):
    if movie_list is None:
        return
    return ', '.join([movie_imdb_link(movie) for movie in movie_list])


register.filter('proposer_format', proposer_format)
register.filter('movie_imdb_link', movie_imdb_link)
register.filter('movie_imdb_link_list', movie_imdb_link_list)
