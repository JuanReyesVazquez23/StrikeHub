"""
Descripción en español de una jugada de béisbol para el marcador en vivo.

La MLB Stats API entrega la jugada ya redactada en inglés ("Junior Lake
grounds out, catcher Maxwell Romero Jr. to first baseman Cristhian Adames.")
y NO se puede pasar por un traductor automático: los motores gratuitos
traducen literal ("Lake aterriza", "Romero camina", "llamó a huelgas") y
terminan destrozando nombres propios, que nunca se deben traducir.

Por eso la frase se arma aquí a partir del evento estructurado
(result.eventType) y del nombre real del bateador. Si el tipo de jugada no
está en la tabla se devuelve None, y quien llama usa la descripción original
en inglés como respaldo: es preferible una jugada en inglés que una jugada
inventada.
"""

# Clave: result.eventType de la MLB Stats API. Valor: frase en español, sin
# punto final; {batter} se reemplaza por el nombre real del bateador.
PLAY_PHRASES_BY_EVENT_TYPE = {
    "single": "{batter} pega sencillo",
    "double": "{batter} pega doble",
    "triple": "{batter} pega triple",
    "home_run": "{batter} conecta jonrón",
    "field_out": "{batter} batea para out",
    "force_out": "{batter} es out por fuerza",
    "fielders_choice": "{batter} llega por selección del fildeador",
    "fielders_choice_out": "{batter} se retira por selección del fildeador",
    "double_play": "{batter} batea para doble play",
    "grounded_into_double_play": "{batter} batea para doble play",
    "triple_play": "{batter} batea para triple play",
    "strikeout": "{batter} se poncha",
    "strikeout_double_play": "{batter} se poncha y es doble play",
    "walk": "{batter} recibe base por bolas",
    "intent_walk": "{batter} recibe base por bolas intencional",
    "hit_by_pitch": "{batter} es golpeado por el pitcheo",
    "field_error": "{batter} llega a base por error",
    "sac_fly": "{batter} batea elevado de sacrificio",
    "sac_fly_double_play": "{batter} batea elevado de sacrificio y es doble play",
    "sac_bunt": "{batter} batea toque de sacrificio",
    "sac_bunt_double_play": "{batter} batea toque de sacrificio y es doble play",
    "catcher_interf": "{batter} llega a base por interferencia del receptor",
    # Jugadas de corrido: aquí el protagonista no es el bateador.
    "stolen_base": "Base robada",
    "caught_stealing": "Atrapado robando base",
    "pickoff": "Out por pickoff",
    "pickoff_caught_stealing": "Atrapado robando base en un pickoff",
    "wild_pitch": "Lanzamiento desviado",
    "passed_ball": "Bola pasada",
    "balk": "Balk",
}


def _rbi_clause(rbi: int) -> str:
    """Cláusula de carreras remolcadas (" y remolca 1 carrera" / "N carreras")."""
    if rbi <= 0:
        return ""
    if rbi == 1:
        return " y remolca 1 carrera"
    return f" y remolca {rbi} carreras"


def describe_play_in_spanish(play: dict | None) -> str | None:
    """
    Devuelve la jugada en español (con punto final) o None si el tipo de
    jugada no está cubierto o si falta el nombre del bateador.

    `play` es una entrada de liveData.plays.allPlays del feed de MLB.
    """
    if not play:
        return None

    result = play.get("result") or {}
    phrase_template = PLAY_PHRASES_BY_EVENT_TYPE.get((result.get("eventType") or "").strip())
    if not phrase_template:
        return None

    batter_name = ((play.get("matchup") or {}).get("batter") or {}).get("fullName")
    if "{batter}" in phrase_template and not batter_name:
        return None

    sentence = phrase_template.format(batter=batter_name)
    rbi = int(result.get("rbi") or 0)
    return f"{sentence}{_rbi_clause(rbi)}."
