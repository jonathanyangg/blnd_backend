# Blend recommendations

`GET /groups/{id}/recommendations` and `/feed` score every candidate once per
member, then combine the scores.

1. **Pool.** pgvector returns 500 candidates near the members' average taste
   embedding, minus anything a member watched, hid, marked "Not for me", or
   saved as interested, and anything on the group watchlist.
2. **Per member.** Each member's score uses their own taste embedding, genres,
   directors, cast, negative embedding and collaborative filtering (CF) from
   their own ratings. A member without enough ratings or co-raters for CF falls
   back to their embedding, which is the onboarding genre seed until they rate.
3. **Equal weight.** A member's scores are standardised over the candidate pool
   before combining, so a heavy rater with CF cannot outvote a light rater.
4. **Combine.** `GROUP_LEAST_MISERY_WEIGHT` (default `0.7`) of the lowest member
   score plus the rest on the mean. `1.0` is pure least misery, `0.0` the mean.
5. **Reason.** Main-algorithm picks carry a `reason` such as "You both rated
   Lady Bird highly". Exploration picks have `reason: null`.

Single-member groups and personal feeds still use the old single-profile path.

`/groups/{id}/pick-tonight` and `/pick-tonight/veto` are deprecated but still
served for iOS 1.1. The first result of `/recommendations` replaces the pick.

Compare old and new scoring with `make eval` (the "Blend feeds" table).
