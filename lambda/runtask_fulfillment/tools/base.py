"""
Base tool interface for Terraform Run Task validators.

This module defines the abstract base class that all tool implementations must extend.
Tools are used by the AI model through Bedrock function calling to validate
infrastructure configurations.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import ToolInput, ToolOutput


class BaseTool(ABC):
    """
    Abstract base class for all validator tools.
    
    Each tool must implement:
    - name: Unique identifier for Bedrock function calling
    - description: Human-readable description for the AI model
    - input_schema: JSON schema defining expected inputs
    - execute: Core validation logic
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """
        Tool name for Bedrock function calling.
        
        Returns:
            Unique tool identifier (e.g., "EC2Validator")
        """
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """
        Tool description for Bedrock AI model.
        
        Returns:
            Human-readable description of what the tool validates
        """
        pass
    
    @property
    @abstractmethod
    def input_schema(self) -> Dict[str, Any]:
        """
        JSON schema for tool inputs.
        
        Returns:
            JSON schema dict defining required and optional input fields
        """
        pass
    
    @abstractmethod
    def execute(self, input_data: ToolInput) -> ToolOutput:
        """
        Execute the tool with given inputs.
        
        Args:
            input_data: Validated input data conforming to input_schema
            
        Returns:
            ToolOutput with success status, findings, and optional error
        """
        pass
    
    def get_bedrock_spec(self) -> Dict[str, Any]:
        """
        Convert tool to Bedrock toolSpec format.
        
        Returns:
            Dict in Bedrock toolSpec format for function calling
        """
        return {
            "toolSpec": {
                "name": self.name,
                "description": self.description,
                "inputSchema": {
                    "json": self.input_schema
                }
            }
        }
