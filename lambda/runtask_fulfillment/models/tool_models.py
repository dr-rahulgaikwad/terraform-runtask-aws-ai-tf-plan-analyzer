"""
Pydantic models for tool inputs and outputs.

This module defines the base models for tool interactions including:
- ToolInput: Base class for tool input validation
- Finding: Security or cost finding with severity and remediation
- ToolOutput: Base class for tool execution results
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


class Severity(str, Enum):
    """Severity levels for findings"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ToolInput(BaseModel):
    """Base class for tool inputs with validation"""
    pass


class Finding(BaseModel):
    """Security or cost finding with remediation guidance"""
    severity: Severity = Field(..., description="Severity level of the finding")
    title: str = Field(..., description="Short title describing the finding")
    description: str = Field(..., description="Detailed description of the issue")
    resource_address: str = Field(..., description="Terraform resource address")
    remediation: str = Field(..., description="Specific steps to remediate the issue")


class ToolOutput(BaseModel):
    """Base class for tool execution results"""
    success: bool = Field(..., description="Whether the tool executed successfully")
    findings: List[Finding] = Field(default_factory=list, description="List of findings from tool execution")
    error: Optional[str] = Field(None, description="Error message if execution failed")
