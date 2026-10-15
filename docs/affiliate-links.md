# Affiliate links

Where-to-watch data is attached to the streaming responses the detail screens
already call. There is no separate where-to-watch route.

- `GET /movies/{tmdb_id}/streaming` keeps its RapidAPI `options` list and adds
  `where_to_watch`.
- `GET /tv/{tmdb_id}/streaming` (only when `TV_SUPPORT_ENABLED` is true) uses
  the same response shape. `options` is empty because the RapidAPI list is
  movie-only. `where_to_watch` is the TMDB payload.
- `GET /out/{provider}/{media_type}/{tmdb_id}` writes a click, then 302s to the
  provider. `{provider}` is the TMDB watch-provider id.

`where_to_watch` is null when the TMDB watch-provider call fails. The movie
`options` list is still returned. Clients that ignore unknown JSON fields keep
working.

```json
{
  "tmdb_id": 550,
  "country": "us",
  "options": [],
  "where_to_watch": {
    "country": "US",
    "attribution": "Data provided by JustWatch",
    "link": "https://www.themoviedb.org/movie/550/watch?locale=US",
    "flatrate": [
      {
        "provider_id": 119,
        "provider_name": "Amazon Prime Video",
        "logo_path": "/prime.jpg",
        "web_url": "https://www.amazon.com/gp/video/search?phrase=Fight%20Club%201999&tag=blndmovies-20",
        "app_url": "aiv://aiv/search?phrase=Fight%20Club%201999"
      }
    ],
    "rent": [],
    "buy": []
  }
}
```

`flatrate` is subscription streaming (where to watch). `rent` and `buy` are the
other two TMDB groups. Offers TMDB labels `ads` or `free` are not returned.
`web_url` is a title-specific https URL (the title plus year). `app_url` is set
only when we have a real app scheme. Amazon https URLs are universal links.

Provider rows are cached for 24 hours in `watch_provider_cache`, one row per
movie or show (TMDB returns every country in one call). Movie id 550 and TV id
550 do not share a row.

## Providers

| TMDB id | Name | Adapter | Tagged when | web_url | app_url |
| --- | --- | --- | --- | --- | --- |
| 119 | Amazon Prime Video | Amazon Associates | `AMAZON_ASSOCIATES_ENABLED` (default true) | `amazon.com/gp/video/search` plus `tag` | `aiv://aiv/search` |
| 10 | Amazon Video | Amazon Associates | same | `amazon.com/s?i=instant-video` plus `tag` | `aiv://aiv/search` |
| 531 | Paramount Plus | Impact stub | `IMPACT_ENABLED` and `IMPACT_PARTNER_ID` | Paramount search plus `subId1` | none |
| 386, 387 | Peacock, Peacock Premium | Impact stub | same | Peacock search plus `subId1` | none |
| 15 | Hulu | Rakuten stub | `RAKUTEN_ENABLED` and `RAKUTEN_PARTNER_ID` | Hulu search plus `ranSiteID` | none |
| 43 | Starz | CJ stub | `CJ_ENABLED` and `CJ_PARTNER_ID` | Starz search plus `sid` | none |
| 283 | Crunchyroll | CJ stub | same | Crunchyroll search plus `sid` | none |
| 2, 350 | Apple TV, Apple TV+ | Apple stub | `APPLE_TV_AFFILIATE_ENABLED` and `APPLE_TV_AFFILIATE_TOKEN` | `tv.apple.com` search plus `at` | none (https is the universal link) |

Anything else TMDB returns uses the passthrough: an untagged link. Registered
providers that are turned off also use the passthrough, so the user still gets
the provider search URL with no partner param. Providers we do not register
link to the TMDB/JustWatch `link` for that country.

Amazon is the only live affiliate adapter. `AMAZON_ASSOCIATES_TAG` defaults to
the public tag `blndmovies-20` when the variable is unset. Set it to an empty
string to leave Amazon links untagged. Set `AMAZON_ASSOCIATES_ENABLED=false`
to force the passthrough.

Impact, Rakuten, and CJ are stubs. They do not wrap the destination in the
network's tracking domain, because that URL has to come from the approved
campaign. Turning one on only appends the partner id to the provider search
URL. Apple's `at` parameter is the real affiliate token, and it stays off
until you set it. Channel add-ons (for example Paramount+ Amazon Channel) are
not registered.

These links are search URLs. TMDB does not give us an Amazon ASIN or a
provider title id, so we cannot build a product page.

## Add a provider

1. Add a `ProviderTarget` in `app/affiliate/providers.py`: TMDB id, display
   name, https search URL with a `{query}` placeholder, and the hosts the
   redirect is allowed to use.
2. Point that id at an adapter. A new network is one `ConfiguredSearchStub`
   (or a class like `AmazonAssociates` when the URL shape is special) plus
   `enabled` and partner-id settings. An existing network is one more id on
   that adapter.
3. Register it in the adapter tuple that fills `REGISTRY`.
4. Add the env vars to `.env.example` and the deployment env. Do not change
   the streaming views, the redirect view, or `links_for`.

`REGISTRY` is the redirect allow-list. `outbound_url` also refuses any URL
whose scheme is not https or whose host is not on that target. A query
parameter cannot choose the destination.

## Clicks

`GET /out/{provider}/{media_type}/{tmdb_id}` requires a logged-in user. The
handler checks the allow-list, builds the URL, inserts `affiliate_clicks`,
commits, and only then returns 302. If the insert fails, there is no redirect.

Columns: `user_id`, `media_type` (`movie` or `tv`), `tmdb_id`, `provider`
(TMDB id), `created_at`.

Row level security is on. `authenticated` can select and insert only rows
whose `user_id` is `auth.uid()`. There is no update or delete policy. The API
connects as the database owner, which bypasses RLS, same as the other tables.
The policies are what stop the public Supabase API from reading every click.

TV redirects 404 while `TV_SUPPORT_ENABLED` is false.

## Disclosure

Show this next to the links, not only in a settings screen:

- FTC: say that some outbound links are affiliate links and that we may earn a
  commission. The relationship has to be clear before the tap.
- JustWatch: TMDB watch-provider data is licensed through JustWatch. Show
  `where_to_watch.attribution` (`Data provided by JustWatch`) with the offers.
  Keep `where_to_watch.link` available. Do not drop the credit when the list
  is rendered.
- Amazon: pages that show Amazon Associates links need a notice such as
  "As an Amazon Associate I earn from qualifying purchases." Follow the
  current Associates operating agreement for placement.
- Apple, Impact, Rakuten, and CJ: follow that network's link and disclosure
  rules once the program is approved. Leave the stub disabled until the
  tracking template is the one the network issued. The stub param is not a
  substitute for an approved deep link.

`/out/...` is first-party click counting. It is not a cloaked affiliate
hopper: the 302 target is the same provider URL returned as `web_url`.
