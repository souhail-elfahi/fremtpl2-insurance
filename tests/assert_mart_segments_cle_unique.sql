-- Une seule ligne par couple (variable, modalite). Renvoie les couples en double.
select variable, modalite, count(*) as n_lignes
from {{ ref('mart_segments') }}
group by variable, modalite
having count(*) > 1
