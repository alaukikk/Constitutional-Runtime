
import math
from dataclasses import dataclass


def _check_number(owner: str, field_name: str, value: float, allow_zero: bool = True) -> None:
    # Registry is config data: negative / NaN / inf would silently make a model look
    # cheaper than it is, so fail loudly at import time.
    if not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"{owner}: {field_name} must be finite and "
                         f"{'>= 0' if allow_zero else '> 0'}, got {value!r}")


@dataclass(frozen=True)
class EnergyAnchor:
    """One measured point: energy for a request of this size."""
    input_tokens: int
    output_tokens: int
    wh: float          # mean energy per request, watt-hours
    wh_std: float      # reported standard deviation (used later for ranges)

    def __post_init__(self) -> None:
        _check_number("EnergyAnchor", "input_tokens", self.input_tokens)
        _check_number("EnergyAnchor", "output_tokens", self.output_tokens)
        if self.input_tokens + self.output_tokens == 0:
            raise ValueError("EnergyAnchor: total tokens must be > 0")
        _check_number("EnergyAnchor", "wh", self.wh, allow_zero=False)
        _check_number("EnergyAnchor", "wh_std", self.wh_std)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ModelInfo:
    name: str                    # Model name #
    provider: str                # Company that provides it #
    cost_per_1k_tokens: float    # How much it costs per 1k tokens #
    typical_latency_ms: float    # How long it tyoically takes to respond #
    capability_score: float      # A how good is it score #
    # Measured energy at several request sizes (interpolated by the estimator).
    # Required on purpose: a default would make a model with no data look free.
    energy_anchors: tuple[EnergyAnchor, ...]
    energy_source: str = ""      # Where the anchors came from (provenance for the audit trail) #

    def __post_init__(self) -> None:
        for f in ("cost_per_1k_tokens", "typical_latency_ms", "capability_score"):
            _check_number(self.name, f, getattr(self, f))
        anchors = tuple(sorted(self.energy_anchors, key=lambda a: a.total_tokens))
        if len(anchors) < 2:
            raise ValueError(f"{self.name}: need at least 2 energy anchors to interpolate")
        totals = [a.total_tokens for a in anchors]
        if len(set(totals)) != len(totals):
            raise ValueError(f"{self.name}: energy anchors must have distinct total token counts")
        self.energy_anchors = anchors


# Energy anchors: How Hungry is AI (Jegham et al.), Table 4, mean +/- std, Wh per request at
# (100 in/300 out), (1k in/1k out), (10k in/1.5k out). These are the paper's estimates for
# proprietary models, not meter readings. GPT-4.1's middle std is printed "0515" in the paper
# (missing decimal point); read as 0.515.
# Names stay "stub-*" so existing code keeps working; each proxies the GPT-4.1 family member below.
# cost / latency / capability are still PLACEHOLDERS (OI-005).
_SIZES = ((100, 300), (1000, 1000), (10000, 1500))


def _anchors(whs, stds):
    return tuple(EnergyAnchor(i, o, w, s) for (i, o), w, s in zip(_SIZES, whs, stds))


MODEL_CATALOG: list[ModelInfo] = [
    ModelInfo("stub-small", "stub", 0.0001, 200, 0.4,
              _anchors((0.207, 0.575, 0.827), (0.047, 0.108, 0.094)),
              "How Hungry is AI, Table 4: GPT-4.1 nano"),
    ModelInfo("stub-medium", "stub", 0.001, 600, 0.7,
              _anchors((0.450, 1.545, 2.122), (0.081, 0.211, 0.348)),
              "How Hungry is AI, Table 4: GPT-4.1 mini"),
    ModelInfo("stub-large", "stub", 0.01, 1500, 0.95,
              _anchors((0.871, 3.161, 4.833), (0.302, 0.515, 0.650)),
              "How Hungry is AI, Table 4: GPT-4.1"),
]
