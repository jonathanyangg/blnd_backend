# Swipe signals

`interested` and `not_for_me` are taste signals. They are not watchlist rows and they are not hides.

Hide stays `POST /recommendations/{tmdb_id}/hide`, which writes `hidden_movies`. That is the hard dislike: the title is removed from recommendation decks and from semantic search, and its embedding enters the negative taste vector at weight **1.0**.

| Signal | Stored in | Positive weight | Negative weight | Personal deck | Semantic search | Watchlist |
| --- | --- | --- | --- | --- | --- | --- |
| Rating | `watched_movies` | the rating (0.5–5) when it is in the user's top tier | `5 - rating` when it is in the bottom 20% and the user has 10+ ratings | excluded | kept | removed on track |
| Watchlist save | `watchlist_movies` | 1.5 | — | excluded | kept | yes |
| `interested` | `movie_interactions` | **1.5** (same as a watchlist save) | — | excluded | kept | no |
| `not_for_me` | `movie_interactions` | — | **0.5** | excluded | kept | no |
| Hide | `hidden_movies` | — | **1.0** | excluded | excluded | no |

`interested` uses the watchlist weight, 1.5, inside the same positive-embedding blend. It does not insert a `watchlist_movies` row. 0.5 on `not_for_me` is half a hide and about one ninth of a 0.5-star rating (`5 - 0.5 = 4.5`).

One row per user and movie. `POST /recommendations/{tmdb_id}/interested` and `POST /recommendations/{tmdb_id}/not-for-me` match hide: authenticated, 200, and a body of `tmdb_id`, `title`, `year`, `poster_path`, plus `interested_at` or `not_for_me_at`. Repeating the same call returns the stored row. `DELETE` on the same path returns 204, or 404 when that signal is not there.

A later swipe replaces the earlier one. A rating or a hide on that same movie wins: the swipe is not added on top. An `interested` swipe on a movie that is also watchlisted counts once, at 1.5.

`sum_weights` on the profile includes these positive weights so match-score leave-one-out subtracts the same weight the embedding used.

The personal deck (`GET /recommendations/me` and the feed) drops swiped titles so the card does not come back. Group recommendations do not hard-exclude a member's `not_for_me` or `interested` titles. Those signals only move the member's taste vector, which the group average already uses. Hide is still union-excluded for the group.

## Item-item collaborative filtering

Collaborative filtering scores candidates from `watched_movies` ratings. Swipes change the taste embedding (candidate search, and the embedding half of a match score). They are not copied into the rating matrix, and they are not turned into fake star ratings.

- `interested`: positive taste weight 1.5, the same as a watchlist save. Leave-one-out subtracts that weight when the embedding cosine is computed, including when that cosine is blended with a CF score. It is not a co-rating. A save and an `interested` swipe on the same title count once, at 1.5.
- `not_for_me`: weight 0.5 on the negative taste vector. It is not a co-rating and not a hide. The pair stays out of the item-item matrix.
- Hide: hard negative, weight 1.0, and the title stays excluded. Not a co-occurrence pair.
- A rating replaces the swipe. The stars are the only collaborative-filtering weight for that user and title.
