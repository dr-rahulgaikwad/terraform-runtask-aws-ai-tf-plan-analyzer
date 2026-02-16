"""
Pydantic models for analysis and run task results.

This module defines the models for aggregated results:
- AnalysisResult: Combined findings and cost impact from all tools
- RunTaskResult: Final result returned to HCP Terraform
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from .tool_models import Finding


class AnalysisResult(BaseModel):
    """Combined analysis result from all tools"""
    findings: List[Finding] = Field(default_factory=list, description="All findings from tool executions")
    cost_impact: Optional[Dict[str, Any]] = Field(None, description="Cost analysis data")
    summary: str = Field(..., description="Human-readable summary of the analysis")


class RunTaskResult(BaseModel):
    """Final result returned to HCP Terraform Run Task API"""
    url: str = Field(..., description="URL for detailed results")
    status: str = Field(..., description="Status: 'passed' or 'failed'")
    message: str = Field(..., description="Summary message for the run task")
    results: List[Dict[str, Any]] = Field(default_factory=list, description="Detailed results array")
