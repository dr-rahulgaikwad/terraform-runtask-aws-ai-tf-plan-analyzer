"""
Checkpoint test to verify all core tools are registered and executable.

This test verifies:
- All validator tools can be instantiated
- All tools can be registered in the ToolRegistry
- All tools have proper Bedrock spec format
- All tools can execute without crashing (basic smoke test)
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch

# Add lambda directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lambda" / "runtask_fulfillment"))

from tools.registry import ToolRegistry
from tools.ec2_validator import EC2ValidatorTool, EC2ValidatorInput
from tools.s3_validator import S3ValidatorTool, S3ValidatorInput
from tools.security_group_validator import SecurityGroupValidatorTool, SecurityGroupValidatorInput
from tools.cost_estimator import CostEstimatorTool, CostEstimatorInput


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset singleton before each test"""
    ToolRegistry.reset()
    yield
    ToolRegistry.reset()


def test_all_tools_can_be_instantiated():
    """Test that all core validator tools can be instantiated"""
    with patch('tools.ec2_validator.boto3.Session'):
        ec2_tool = EC2ValidatorTool()
        assert ec2_tool is not None
        assert ec2_tool.name == "EC2Validator"
    
    s3_tool = S3ValidatorTool()
    assert s3_tool is not None
    assert s3_tool.name == "S3Validator"
    
    sg_tool = SecurityGroupValidatorTool()
    assert sg_tool is not None
    assert sg_tool.name == "SecurityGroupValidator"
    
    with patch('tools.cost_estimator.boto3.Session'):
        cost_tool = CostEstimatorTool()
        assert cost_tool is not None
        assert cost_tool.name == "CostEstimator"


def test_all_tools_can_be_registered():
    """Test that all tools can be registered in the ToolRegistry"""
    registry = ToolRegistry()
    
    with patch('tools.ec2_validator.boto3.Session'):
        ec2_tool = EC2ValidatorTool()
        registry.register(ec2_tool)
    
    s3_tool = S3ValidatorTool()
    registry.register(s3_tool)
    
    sg_tool = SecurityGroupValidatorTool()
    registry.register(sg_tool)
    
    with patch('tools.cost_estimator.boto3.Session'):
        cost_tool = CostEstimatorTool()
        registry.register(cost_tool)
    
    # Verify all tools are registered
    tools = registry.list_tools()
    assert len(tools) == 4
    assert "EC2Validator" in tools
    assert "S3Validator" in tools
    assert "SecurityGroupValidator" in tools
    assert "CostEstimator" in tools


def test_all_tools_have_valid_bedrock_spec():
    """Test that all tools generate valid Bedrock toolSpec format"""
    registry = ToolRegistry()
    
    with patch('tools.ec2_validator.boto3.Session'):
        registry.register(EC2ValidatorTool())
    
    registry.register(S3ValidatorTool())
    registry.register(SecurityGroupValidatorTool())
    
    with patch('tools.cost_estimator.boto3.Session'):
        registry.register(CostEstimatorTool())
    
    # Get Bedrock spec
    specs = registry.to_bedrock_spec()
    
    assert len(specs) == 4
    
    # Verify each spec has correct structure
    for spec in specs:
        assert "toolSpec" in spec
        assert "name" in spec["toolSpec"]
        assert "description" in spec["toolSpec"]
        assert "inputSchema" in spec["toolSpec"]
        assert "json" in spec["toolSpec"]["inputSchema"]
        
        # Verify input schema structure
        input_schema = spec["toolSpec"]["inputSchema"]["json"]
        assert "type" in input_schema
        assert input_schema["type"] == "object"
        assert "properties" in input_schema


def test_ec2_validator_basic_execution():
    """Test EC2Validator can execute without crashing"""
    with patch('tools.ec2_validator.boto3.Session'):
        tool = EC2ValidatorTool()
        
        # Mock EC2 client
        mock_client = Mock()
        mock_client.describe_instance_types.return_value = {
            'InstanceTypes': [{'InstanceType': 't3.micro'}]
        }
        
        with patch.object(tool.session, 'client', return_value=mock_client):
            input_data = EC2ValidatorInput(
                instance_type="t3.micro",
                region="us-east-1"
            )
            
            result = tool.execute(input_data)
            
            assert result is not None
            assert hasattr(result, 'success')
            assert hasattr(result, 'findings')


def test_s3_validator_basic_execution():
    """Test S3Validator can execute without crashing"""
    tool = S3ValidatorTool()
    
    input_data = S3ValidatorInput(
        bucket_name="test-bucket",
        public_access_block={
            "block_public_acls": True,
            "block_public_policy": True,
            "ignore_public_acls": True,
            "restrict_public_buckets": True
        },
        encryption={
            "sse_algorithm": "AES256"
        }
    )
    
    result = tool.execute(input_data)
    
    assert result is not None
    assert hasattr(result, 'success')
    assert hasattr(result, 'findings')
    assert result.success is True


def test_security_group_validator_basic_execution():
    """Test SecurityGroupValidator can execute without crashing"""
    tool = SecurityGroupValidatorTool()
    
    input_data = SecurityGroupValidatorInput(
        security_group_name="test-sg",
        ingress_rules=[
            {
                "from_port": 80,
                "to_port": 80,
                "protocol": "tcp",
                "cidr_blocks": ["0.0.0.0/0"]
            }
        ],
        egress_rules=[]
    )
    
    result = tool.execute(input_data)
    
    assert result is not None
    assert hasattr(result, 'success')
    assert hasattr(result, 'findings')
    assert result.success is True


def test_cost_estimator_basic_execution():
    """Test CostEstimator can execute without crashing"""
    with patch('tools.cost_estimator.boto3.Session'):
        tool = CostEstimatorTool()
        
        # Mock pricing client to avoid actual API calls
        with patch.object(tool, '_get_pricing_from_api', return_value=None):
            input_data = CostEstimatorInput(
                instance_type="t3.micro",
                region="us-east-1",
                hours_per_month=730
            )
            
            result = tool.execute(input_data)
            
            assert result is not None
            assert hasattr(result, 'success')
            assert hasattr(result, 'findings')
            assert result.success is True


def test_all_tools_return_proper_output_format():
    """Test that all tools return ToolOutput with correct structure"""
    registry = ToolRegistry()
    
    with patch('tools.ec2_validator.boto3.Session'):
        registry.register(EC2ValidatorTool())
    
    registry.register(S3ValidatorTool())
    registry.register(SecurityGroupValidatorTool())
    
    with patch('tools.cost_estimator.boto3.Session'):
        registry.register(CostEstimatorTool())
    
    # Verify each tool can be retrieved
    for tool_name in ["EC2Validator", "S3Validator", "SecurityGroupValidator", "CostEstimator"]:
        tool = registry.get_tool(tool_name)
        assert tool is not None
        assert hasattr(tool, 'execute')
        assert hasattr(tool, 'name')
        assert hasattr(tool, 'description')
        assert hasattr(tool, 'input_schema')


def test_registry_bedrock_spec_tool_names():
    """Test that Bedrock spec contains all expected tool names"""
    registry = ToolRegistry()
    
    with patch('tools.ec2_validator.boto3.Session'):
        registry.register(EC2ValidatorTool())
    
    registry.register(S3ValidatorTool())
    registry.register(SecurityGroupValidatorTool())
    
    with patch('tools.cost_estimator.boto3.Session'):
        registry.register(CostEstimatorTool())
    
    specs = registry.to_bedrock_spec()
    tool_names = [spec["toolSpec"]["name"] for spec in specs]
    
    assert "EC2Validator" in tool_names
    assert "S3Validator" in tool_names
    assert "SecurityGroupValidator" in tool_names
    assert "CostEstimator" in tool_names
