-- Pour chaque variable, la somme des expositions égale l'exposition totale du mart.
-- Tolérance : les sommes de nombres décimaux diffèrent selon l'ordre d'addition.
with total as (
    select sum(exposure_capped) as exposition
    from {{ ref('mart_policy_claims') }}
)

select s.variable, sum(s.exposition) as somme_segments, t.exposition as total_mart
from {{ ref('mart_segments') }} as s
cross join total as t
group by s.variable, t.exposition
having abs(sum(s.exposition) - t.exposition) > 0.000001
