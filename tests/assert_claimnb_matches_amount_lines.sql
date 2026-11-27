-- Contrats avec montant dont le nombre déclaré diffère du nombre de lignes de montant.
{{ config(severity='warn') }}

select IDpol, ClaimNb, n_amount_lines
from {{ ref('mart_policy_claims') }}
where has_amount
  and ClaimNb <> n_amount_lines
