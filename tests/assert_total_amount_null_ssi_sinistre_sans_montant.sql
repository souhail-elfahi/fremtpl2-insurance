-- total_amount (et sa version écrêtée) est NULL si et seulement si
-- le contrat est sinistré et n'a aucune ligne de montant. Renvoie les contrats fautifs.
select IDpol, ClaimNb, n_amount_lines, total_amount, total_amount_capped
from {{ ref('mart_policy_claims') }}
where (total_amount is null) <> (ClaimNb > 0 and n_amount_lines = 0)
   or (total_amount_capped is null) <> (ClaimNb > 0 and n_amount_lines = 0)
