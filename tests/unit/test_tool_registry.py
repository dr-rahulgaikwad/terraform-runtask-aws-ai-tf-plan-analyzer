"""
Unit tests for ToolRegistry class.

Tests cover:
- Singleton pattern behavior
- Thread-safe registration
- Tool retrieval and listing
- Bedrock spec conversion
- Error handling
"""

import pytest
import threading
import sys
from pathlib import Path

# Add lambda directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lambda" / "runtask_fulfillment"))

from tools.registry import ToolRegistry
from tools.base import BaseTool
from models.tool_models import ToolInput, ToolOutput, Finding, Severity


class MockTool(BaseTool):
    """Mock tool for testing"""
    
    def __init__(self, tool_name: str = "MockTool"):
        self._name = tool_name
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def description(self) -> str:
        return "A mock tool for testing"
    
    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "test_input": {"type": "string"}
            },
            "required": ["test_input"]
        }
    
    def execute(self, input_data: ToolInput) -> ToolOutput:
        return ToolOutput(success=True, findings=[])


class IncompleteTool(BaseTool):
    """Tool missing required properties"""
    
    @property
    def name(self) -> str:
        return "IncompleteTool"
    
    @property
    def description(self) -> str:
        raise NotImplementedError("Description not implemented")
    
    @property
    def input_schema(self) -> dict:
        return {}
    
    def execute(self, input_data: ToolInput) -> ToolOutput:
        return ToolOutput(success=True, findings=[])


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset singleton before each test"""
    ToolRegistry.reset()
    yield
    ToolRegistry.reset()


def test_singleton_pattern():
    """Test that ToolRegistry implements singleton pattern correctly"""
    registry1 = ToolRegistry()
    registry2 = ToolRegistry()
    
    assert registry1 is registry2, "ToolRegistry should return same instance"


def test_singleton_thread_safety():
    """Test that singleton creation is thread-safe"""
    instances = []
    
    def create_instance():
        instances.append(ToolRegistry())
    
    threads = [threading.Thread(target=create_instance) for _ in range(10)]
    
    for thread in threads:
        thread.start()
    
    for thread in threads:
        thread.join()
    
    # All instances should be the same object
    assert all(inst is instances[0] for inst in instances), "All instances should be identical"


def test_register_tool():
    """Test registering a valid tool"""
    registry = ToolRegistry()
    tool = MockTool("TestTool")
    
    registry.register(tool)
    
    assert "TestTool" in registry.list_tools()
    assert registry.get_tool("TestTool") is tool


def test_register_duplicate_tool():
    """Test that registering duplicate tool raises ValueError"""
    registry = ToolRegistry()
    tool1 = MockTool("DuplicateTool")
    tool2 = MockTool("DuplicateTool")
    
    registry.register(tool1)
    
    with pytest.raises(ValueError, match="already registered"):
        registry.register(tool2)


def test_register_invalid_tool():
    """Test that registering non-BaseTool raises TypeError"""
    registry = ToolRegistry()
    
    with pytest.raises(TypeError, match="must implement BaseTool"):
        registry.register("not a tool")


def test_register_incomplete_tool():
    """Test that registering tool with missing properties raises ValueError"""
    registry = ToolRegistry()
    tool = IncompleteTool()
    
    with pytest.raises(ValueError, match="missing required properties"):
        registry.register(tool)


def test_get_tool():
    """Test retrieving a registered tool"""
    registry = ToolRegistry()
    tool = MockTool("GetTool")
    
    registry.register(tool)
    
    retrieved = registry.get_tool("GetTool")
    assert retrieved is tool


def test_get_nonexistent_tool():
    """Test retrieving a tool that doesn't exist returns None"""
    registry = ToolRegistry()
    
    result = registry.get_tool("NonexistentTool")
    assert result is None


def test_list_tools():
    """Test listing all registered tools"""
    registry = ToolRegistry()
    
    tool1 = MockTool("Tool1")
    tool2 = MockTool("Tool2")
    tool3 = MockTool("Tool3")
    
    registry.register(tool1)
    registry.register(tool2)
    registry.register(tool3)
    
    tools = registry.list_tools()
    
    assert len(tools) == 3
    assert "Tool1" in tools
    assert "Tool2" in tools
    assert "Tool3" in tools


def test_list_tools_empty():
    """Test listing tools when registry is empty"""
    registry = ToolRegistry()
    
    tools = registry.list_tools()
    assert tools == []


def test_to_bedrock_spec():
    """Test converting registry to Bedrock toolSpec format"""
    registry = ToolRegistry()
    tool = MockTool("BedrockTool")
    
    registry.register(tool)
    
    specs = registry.to_bedrock_spec()
    
    assert len(specs) == 1
    assert "toolSpec" in specs[0]
    assert specs[0]["toolSpec"]["name"] == "BedrockTool"
    assert specs[0]["toolSpec"]["description"] == "A mock tool for testing"
    assert "inputSchema" in specs[0]["toolSpec"]
    assert "json" in specs[0]["toolSpec"]["inputSchema"]


def test_to_bedrock_spec_multiple_tools():
    """Test converting multiple tools to Bedrock format"""
    registry = ToolRegistry()
    
    tool1 = MockTool("Tool1")
    tool2 = MockTool("Tool2")
    
    registry.register(tool1)
    registry.register(tool2)
    
    specs = registry.to_bedrock_spec()
    
    assert len(specs) == 2
    tool_names = [spec["toolSpec"]["name"] for spec in specs]
    assert "Tool1" in tool_names
    assert "Tool2" in tool_names


def test_to_bedrock_spec_empty():
    """Test converting empty registry to Bedrock format"""
    registry = ToolRegistry()
    
    specs = registry.to_bedrock_spec()
    assert specs == []


def test_thread_safe_registration():
    """Test that tool registration is thread-safe"""
    registry = ToolRegistry()
    errors = []
    
    def register_tool(tool_name: str):
        try:
            tool = MockTool(tool_name)
            registry.register(tool)
        except Exception as e:
            errors.append(e)
    
    threads = [
        threading.Thread(target=register_tool, args=(f"Tool{i}",))
        for i in range(10)
    ]
    
    for thread in threads:
        thread.start()
    
    for thread in threads:
        thread.join()
    
    # Should have no errors
    assert len(errors) == 0
    
    # Should have all 10 tools registered
    assert len(registry.list_tools()) == 10


def test_bedrock_spec_format():
    """Test that Bedrock spec has correct structure"""
    registry = ToolRegistry()
    tool = MockTool("SpecTool")
    
    registry.register(tool)
    
    specs = registry.to_bedrock_spec()
    spec = specs[0]
    
    # Validate structure
    assert isinstance(spec, dict)
    assert "toolSpec" in spec
    
    tool_spec = spec["toolSpec"]
    assert "name" in tool_spec
    assert "description" in tool_spec
    assert "inputSchema" in tool_spec
    
    input_schema = tool_spec["inputSchema"]
    assert "json" in input_schema
    assert isinstance(input_schema["json"], dict)
