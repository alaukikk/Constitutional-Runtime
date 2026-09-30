
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RequestType(str, Enum):                    # What kind of requst is this? #
    LOOKUP = "lookup"
    COMPUTATION = "computation"
    CLASSIFICATION = "classification"
    GENERATION = "generation"
    JUDGMENT = "judgment"
    HIGH_STAKES = "high_stakes"
    UNKNOWN = "unknown"


class MethodTier(str, Enum):                    # Ways to answer a question, ordered cheapest to expensive #
    CACHE = "cache_lookup"
    DETERMINISTIC = "deterministic"
    SMALL_CLASSIFIER = "small_classifier"
    RAG_SMALL_MODEL = "rag_small_model"
    LLM_LOW_REASONING = "llm_low_reasoning"
    LLM_HIGH_REASONING = "llm_high_reasoning"


class RiskCategory(str, Enum):                    # Risk type #
    DANGEROUS_CONTENT = "dangerous_content"
    DATA_PRIVACY = "data_privacy"
    HUMAN_AI_CONFIG = "human_ai_configuration"


class PolicyAction(str, Enum):                    # Possible outcomes when a policy rule gets triggered# 
    ALLOW = "allow"
    FLAG = "flag"
    REQUIRE_HUMAN = "require_human"
    BLOCK = "block"


@dataclass
class PolicyFlag:
    rule_id: str                                  # What rule was triggerd #
    risk_category: RiskCategory                   # What kind of risk it is #
    action: PolicyAction                          # Action to be taken #
    reason: str                                   # Reason for the action #


@dataclass
class RequestClassification:                      # Result of figuring out the kind of request and confidence score #      
    category: RequestType
    confidence: float = 0.0
    raw_text: str = ""


@dataclass
class TierCostEstimate:                          #How much the chosen option would cost #
    tier: MethodTier
    model_name: Optional[str] = None
    est_dollar_cost: float = 0.0
    est_latency_ms: float = 0.0
    est_energy_wh: float = 0.0                   # Estimated energy in watt-hours (appended last: old positional calls still work) #


@dataclass
class RoutingDecision:                          # Final output of the whole decision making process #
    selected_tier: MethodTier
    selected_model: Optional[str]
    rationale: str
    cost_estimate: TierCostEstimate
    policy_flags: list[PolicyFlag] = field(default_factory=list)
