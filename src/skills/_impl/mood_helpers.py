def morning_reset(state):
    # Regression toward Lumi's baseline
    # Baseline: mood_valence=0.3, mood_energy=0.6, irritation=0.0, focus=0.7
    state["mood_valence"]  = lerp(state["mood_valence"],  0.3, 0.4)
    state["mood_energy"]   = lerp(state["mood_energy"],   0.6, 0.5)  # sleep restores energy faster
    state["irritation"]    = lerp(state["irritation"],    0.0, 0.6)  # irritation fades fastest overnight
    state["focus_level"]   = lerp(state["focus_level"],   0.7, 0.4)
    # trust_jose does NOT regress — it persists
    state["last_day_reset"] = now_iso()
    return state


def state_to_text(state: dict) -> str:
    valence_desc = (
        "algo seria"   if state["mood_valence"] < 0.0 else
        "neutra"       if state["mood_valence"] < 0.3 else
        "de buen humor" if state["mood_valence"] < 0.7 else
        "muy animada"
    )
    energy_desc = (
        "cansada" if state["mood_energy"] < 0.3 else
        "normal"  if state["mood_energy"] < 0.6 else
        "con energía"
    )
    irrit_desc = "" if state["irritation"] < 0.3 else (
        ", con algo de fastidio acumulado" if state["irritation"] < 0.6 else
        ", bastante fastidiada"
    )
    return f"Estado interno actual de Lumi: {valence_desc}, {energy_desc}{irrit_desc}."