-- Test réutilisable : renvoie les lignes fautives (valeur nulle, égale à 0 ou négative).
{% test strictly_positive(model, column_name) %}

select {{ column_name }}
from {{ model }}
where {{ column_name }} is null or {{ column_name }} <= 0

{% endtest %}
