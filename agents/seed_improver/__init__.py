from .service import SeedImproverService, SeedImproverResult
from .analyzer import SeedImproverAnalyzer
from .auto_apply import AutoApplyPipeline
from .deployer import SelfDeployer
from .safety import SafetyValidator
from .models import AnalysisResult, Recommendation, PatternMatch, ExpectedImpact, ConfigPatch, AutoApplyResult
from .population import PopulationArchive
from .fitness import FitnessEvaluator
from .selection import ParentSelector
from .judge import VariantJudge

try:
    from .dgm_service import DGMService
except ImportError:
    DGMService = None  # type: ignore[assignment,misc]

__all__ = [
    "SeedImproverService",
    "SeedImproverResult",
    "SeedImproverAnalyzer",
    "AutoApplyPipeline",
    "SelfDeployer",
    "SafetyValidator",
    "AnalysisResult",
    "Recommendation",
    "PatternMatch",
    "ExpectedImpact",
    "ConfigPatch",
    "AutoApplyResult",
    "PopulationArchive",
    "FitnessEvaluator",
    "ParentSelector",
    "VariantJudge",
    "DGMService",
]
