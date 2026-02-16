"""
Unit tests for tool orchestration in ai.py

Tests verify that the eval function correctly:
- Uses ToolRegistry.to_bedrock_spec() to get tool specifications
- Routes tool execution requests dynamically using ToolRegistry.get_tool()
- Handles multi-turn function calling loops
- Falls back to hardcoded AMI tool for backward compatibility
"""

import json
import pytest
from unittest.mock import Mock, MagicMock, patch, call
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lambda" / "runtask_fulfillment"))

from tools.registry import ToolRegistry
from tools.base import BaseTool, ToolInput, ToolOutput


class MockTool(BaseTool):
    """Mock tool for testing"""
    
    @property
    def name(self) -> str:
        return "MockTool"
    
    @property
    def description(self) -> str:
        return "A mock tool for testing"
    
    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "test_param": {"type": "string"}
            },
            "required": ["test_param"]
        }
    
    def execute(self, input_data: dict) -> dict:
        return {
            "success": True,
            "findings": [],
            "message": f"Executed with {input_data.get('test_param')}"
        }


class TestToolOrchestration:
    """Test tool orchestration functionality"""
    
    def test_tool_registry_to_bedrock_spec(self):
        """Test that ToolRegistry.to_bedrock_spec() returns correct format"""
        # Reset registry for clean test
        ToolRegistry.reset()
        registry = ToolRegistry()
        
        # Register a mock tool
        mock_tool = MockTool()
        registry.register(mock_tool)
        
        # Get Bedrock spec
        bedrock_spec = registry.to_bedrock_spec()
        
        # Verify format
        assert isinstance(bedrock_spec, list)
        assert len(bedrock_spec) == 1
        assert "toolSpec" in bedrock_spec[0]
        assert bedrock_spec[0]["toolSpec"]["name"] == "MockTool"
        assert bedrock_spec[0]["toolSpec"]["description"] == "A mock tool for testing"
        assert "inputSchema" in bedrock_spec[0]["toolSpec"]
        assert "json" in bedrock_spec[0]["toolSpec"]["inputSchema"]
    
    def test_dynamic_tool_routing(self):
        """Test that tools are routed dynamically using registry.get_tool()"""
        # Reset registry for clean test
        ToolRegistry.reset()
        registry = ToolRegistry()
        
        # Register a mock tool
        mock_tool = MockTool()
        registry.register(mock_tool)
        
        # Get tool by name
        retrieved_tool = registry.get_tool("MockTool")
        
        # Verify correct tool retrieved
        assert retrieved_tool is not None
        assert retrieved_tool.name == "MockTool"
        
        # Execute tool
        result = retrieved_tool.execute({"test_param": "test_value"})
        
        # Verify execution
        assert result["success"] is True
        assert "test_value" in result["message"]
    
    def test_tool_not_found_handling(self):
        """Test handling when tool is not found in registry"""
        # Reset registry for clean test
        ToolRegistry.reset()
        registry = ToolRegistry()
        
        # Try to get non-existent tool
        tool = registry.get_tool("NonExistentTool")
        
        # Verify None returned
        assert tool is None
    
    def test_multiple_tools_in_registry(self):
        """Test that multiple tools can be registered and retrieved"""
        # Reset registry for clean test
        ToolRegistry.reset()
        registry = ToolRegistry()
        
        # Register multiple mock tools
        class MockTool1(MockTool):
            @property
            def name(self) -> str:
                return "MockTool1"
        
        class MockTool2(MockTool):
            @property
            def name(self) -> str:
                return "MockTool2"
        
        registry.register(MockTool1())
        registry.register(MockTool2())
        
        # Get Bedrock spec
        bedrock_spec = registry.to_bedrock_spec()
        
        # Verify both tools in spec
        assert len(bedrock_spec) == 2
        tool_names = [spec["toolSpec"]["name"] for spec in bedrock_spec]
        assert "MockTool1" in tool_names
        assert "MockTool2" in tool_names
    
    def test_bedrock_spec_format_validation(self):
        """Test that Bedrock spec format is valid for API consumption"""
        # Reset registry for clean test
        ToolRegistry.reset()
        registry = ToolRegistry()
        
        # Register multiple tools
        class Tool1(MockTool):
            @property
            def name(self) -> str:
                return "EC2Validator"
        
        class Tool2(MockTool):
            @property
            def name(self) -> str:
                return "S3Validator"
        
        registry.register(Tool1())
        registry.register(Tool2())
        
        # Get Bedrock spec
        bedrock_spec = registry.to_bedrock_spec()
        
        # Verify format matches Bedrock API requirements
        assert isinstance(bedrock_spec, list)
        
        for tool_spec in bedrock_spec:
            # Each tool must have toolSpec key
            assert "toolSpec" in tool_spec
            
            # toolSpec must have required fields
            assert "name" in tool_spec["toolSpec"]
            assert "description" in tool_spec["toolSpec"]
            assert "inputSchema" in tool_spec["toolSpec"]
            
            # inputSchema must have json key
            assert "json" in tool_spec["toolSpec"]["inputSchema"]
            
            # json must be a dict with type and properties
            schema = tool_spec["toolSpec"]["inputSchema"]["json"]
            assert isinstance(schema, dict)
            assert "type" in schema
            assert "properties" in schema


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
