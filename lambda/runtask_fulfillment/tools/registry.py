"""
Tool Registry for managing available validator tools.

This module implements a thread-safe singleton registry that maintains
a collection of available tools and converts them to Bedrock toolSpec format.

Requirements: 1.1, 1.2, 1.3
"""

import threading
from typing import Dict, List, Optional, Any
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.base import BaseTool


class ToolRegistry:
    """
    Thread-safe singleton registry for managing validator tools.
    
    The registry maintains a collection of tools and provides methods to:
    - Register new tools
    - Retrieve tools by name
    - List all available tools
    - Convert the registry to Bedrock toolSpec format
    
    Thread Safety:
        Uses double-checked locking pattern for singleton instantiation
        and a lock for thread-safe tool registration.
    """
    
    _instance: Optional['ToolRegistry'] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> 'ToolRegistry':
        """
        Create or return the singleton instance using double-checked locking.
        
        Returns:
            The singleton ToolRegistry instance
        """
        if cls._instance is None:
            with cls._lock:
                # Double-check after acquiring lock
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize the registry (only runs once for singleton)"""
        if self._initialized:
            return
        
        self._tools: Dict[str, BaseTool] = {}
        self._registry_lock: threading.Lock = threading.Lock()
        self._initialized = True
    
    def register(self, tool: BaseTool) -> None:
        """
        Register a tool with the registry.
        
        Validates that the tool implements the required interface and
        stores it in the registry by name.
        
        Args:
            tool: Tool instance implementing BaseTool interface
            
        Raises:
            TypeError: If tool doesn't implement BaseTool
            ValueError: If tool with same name already registered
        """
        if not isinstance(tool, BaseTool):
            raise TypeError(f"Tool must implement BaseTool interface, got {type(tool)}")
        
        tool_name = tool.name
        
        with self._registry_lock:
            if tool_name in self._tools:
                raise ValueError(f"Tool '{tool_name}' is already registered")
            
            # Validate tool has required properties
            try:
                _ = tool.description
                _ = tool.input_schema
            except (AttributeError, NotImplementedError) as e:
                raise ValueError(f"Tool '{tool_name}' missing required properties: {e}")
            
            self._tools[tool_name] = tool
    
    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        """
        Retrieve a tool by name.
        
        Args:
            tool_name: Name of the tool to retrieve
            
        Returns:
            Tool instance if found, None otherwise
        """
        with self._registry_lock:
            return self._tools.get(tool_name)
    
    def list_tools(self) -> List[str]:
        """
        List all registered tool names.
        
        Returns:
            List of tool names in registration order
        """
        with self._registry_lock:
            return list(self._tools.keys())
    
    def to_bedrock_spec(self) -> List[Dict[str, Any]]:
        """
        Convert registry to Bedrock toolSpec format.
        
        Converts all registered tools to the format expected by
        Amazon Bedrock's function calling API.
        
        Returns:
            List of tool specifications in Bedrock format:
            [
                {
                    "toolSpec": {
                        "name": "ToolName",
                        "description": "Tool description",
                        "inputSchema": {"json": {...}}
                    }
                },
                ...
            ]
        """
        with self._registry_lock:
            return [tool.get_bedrock_spec() for tool in self._tools.values()]
    
    @classmethod
    def reset(cls) -> None:
        """
        Reset the singleton instance (primarily for testing).
        
        Warning:
            This method should only be used in test scenarios.
            Using it in production code can lead to unexpected behavior.
        """
        with cls._lock:
            cls._instance = None
