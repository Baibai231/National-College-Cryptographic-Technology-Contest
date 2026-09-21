"""One evaluation contract, explicit optional failures, no model substitution."""
from core.attackers import BaselineAttacker, FrequencyAttacker, SyntheticDictionaryAttacker, CharacterNgramAttacker
from ai.pcfg_adapter import PCFGAttacker


class OptionalAttackerFailed(RuntimeError):
    def __init__(self, attacker_id, error):
        self.attacker_id = attacker_id
        self.reason = f"{type(error).__name__}: {error}"
        super().__init__(self.reason)


class CheckedAttacker(BaselineAttacker):
    def __init__(self, attacker, mode):
        self.inner = attacker
        self.attacker_id, self.label, self.version = attacker.attacker_id, attacker.label, attacker.version
        self.mode = mode

    def fit_select_rank(self, train, validation, candidates):
        try:
            return self.inner.fit_select_rank(train, validation, candidates)
        except Exception as exc:
            if self.mode == "optional":
                raise OptionalAttackerFailed(self.attacker_id, exc) from exc
            raise RuntimeError(f"必选攻击器 {self.attacker_id} 失败：{exc}") from exc


def build_attackers(config, pcfg_config, *, excluded=(), search=False):
    ngram = config["ngram"]
    factories = {
        "frequency": FrequencyAttacker,
        "synthetic-dictionary": SyntheticDictionaryAttacker,
        "character-ngram": lambda: CharacterNgramAttacker(
            orders=tuple(ngram["search_orders" if search else "orders"]),
            smoothing_values=tuple(ngram["search_smoothing_values" if search else "smoothing_values"])),
        "pcfg": lambda: PCFGAttacker(pcfg_config),
    }
    return tuple(CheckedAttacker(factories[name](), mode)
                 for name, mode in config["attackers"].items() if name not in excluded)
