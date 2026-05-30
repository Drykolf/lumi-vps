"""
Capa de auto-evolución de Lumi (Fase A/C — cimientos).

Expone el injector que recupera tastes/rules consolidados por similitud semántica
para inyectarlos al prompt. La creación de nuevas entries (pipeline nocturno) y el
Opinion Engine son fases posteriores y aún no viven aquí.
"""
from agent.evolution.injection import EvolutionInjector, get_injector

__all__ = ["EvolutionInjector", "get_injector"]
