"""
Unit tests for EC2ValidatorTool.

Tests cover:
- Instance type validation
- AMI validation
- Error handling
- Bedrock spec generation
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path
from botocore.exceptions import ClientError

# Add lambda directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "lambda" / "runtask_fulfillment"))

from tools.ec2_validator import EC2ValidatorTool, EC2ValidatorInput
from models.tool_models import ToolOutput, Finding, Severity


@pytest.fixture
def ec2_validator():
    """Create EC2ValidatorTool instance with mocked AWS clients"""
    with patch('tools.ec2_validator.boto3.Session'):
        tool = EC2ValidatorTool()
        return tool


@pytest.fixture
def mock_ec2_client():
    """Create mock EC2 client"""
    client = Mock()
    return client


def test_tool_properties(ec2_validator):
    """Test that tool has required properties"""
    assert ec2_validator.name == "EC2Validator"
    assert isinstance(ec2_validator.description, str)
    assert len(ec2_validator.description) > 0
    assert isinstance(ec2_validator.input_schema, dict)
    assert "properties" in ec2_validator.input_schema


def test_input_schema_structure(ec2_validator):
    """Test that input schema has correct structure"""
    schema = ec2_validator.input_schema
    
    assert schema["type"] == "object"
    assert "instance_type" in schema["properties"]
    assert "region" in schema["properties"]
    assert "ami_id" in schema["properties"]
    assert "instance_type" in schema["required"]
    assert "region" in schema["required"]


def test_bedrock_spec_format(ec2_validator):
    """Test that Bedrock spec has correct format"""
    spec = ec2_validator.get_bedrock_spec()
    
    assert "toolSpec" in spec
    assert spec["toolSpec"]["name"] == "EC2Validator"
    assert "description" in spec["toolSpec"]
    assert "inputSchema" in spec["toolSpec"]
    assert "json" in spec["toolSpec"]["inputSchema"]


def test_execute_with_valid_instance_type(ec2_validator, mock_ec2_client):
    """Test execution with valid instance type"""
    # Mock EC2 client response
    mock_ec2_client.describe_instance_types.return_value = {
        'InstanceTypes': [
            {
                'InstanceType': 't3.micro',
                'VCpuInfo': {'DefaultVCpus': 2}
            }
        ]
    }
    
    with patch.object(ec2_validator.session, 'client', return_value=mock_ec2_client):
        input_data = EC2ValidatorInput(
            instance_type="t3.micro",
            region="us-east-1"
        )
        
        result = ec2_validator.execute(input_data)
        
        assert result.success is True
        assert isinstance(result.findings, list)
        # Valid instance type should have no findings
        assert len(result.findings) == 0


def test_execute_with_unavailable_instance_type(ec2_validator, mock_ec2_client):
    """Test execution with instance type not available in region"""
    # Mock EC2 client response with empty list
    mock_ec2_client.describe_instance_types.return_value = {
        'InstanceTypes': []
    }
    
    with patch.object(ec2_validator.session, 'client', return_value=mock_ec2_client):
        input_data = EC2ValidatorInput(
            instance_type="t3.micro",
            region="us-west-1"
        )
        
        result = ec2_validator.execute(input_data)
        
        assert result.success is True
        assert len(result.findings) == 1
        
        finding = result.findings[0]
        assert finding.severity == Severity.HIGH
        assert "not available" in finding.title.lower()
        assert "t3.micro" in finding.title
        assert "us-west-1" in finding.title


def test_execute_with_invalid_instance_type(ec2_validator, mock_ec2_client):
    """Test execution with invalid instance type"""
    # Mock ClientError for invalid instance type
    error_response = {
        'Error': {
            'Code': 'InvalidInstanceType',
            'Message': 'Invalid instance type'
        }
    }
    mock_ec2_client.describe_instance_types.side_effect = ClientError(
        error_response, 'DescribeInstanceTypes'
    )
    
    with patch.object(ec2_validator.session, 'client', return_value=mock_ec2_client):
        input_data = EC2ValidatorInput(
            instance_type="invalid.type",
            region="us-east-1"
        )
        
        result = ec2_validator.execute(input_data)
        
        assert result.success is True
        assert len(result.findings) == 1
        
        finding = result.findings[0]
        assert finding.severity == Severity.CRITICAL
        assert "invalid" in finding.title.lower()


def test_execute_with_ami_id(ec2_validator, mock_ec2_client):
    """Test execution with AMI ID provided"""
    # Mock EC2 client response
    mock_ec2_client.describe_instance_types.return_value = {
        'InstanceTypes': [{'InstanceType': 't3.micro'}]
    }
    
    # Mock AMI validator
    mock_ami_releases = [
        {
            'ami_id': 'ami-12345',
            'ami_name': 'amzn2-ami-ecs-hvm-2.0.20230101-x86_64-ebs',
            'os_name': 'Amazon ECS-optimized Amazon Linux 2 AMI'
        }
    ]
    
    # Mock the ami_validator property to avoid importing get_ami_releases
    mock_ami_validator = Mock()
    mock_ami_validator.execute.return_value = mock_ami_releases
    
    with patch.object(ec2_validator.session, 'client', return_value=mock_ec2_client):
        with patch.object(type(ec2_validator), 'ami_validator', new_callable=lambda: property(lambda self: mock_ami_validator)):
            input_data = EC2ValidatorInput(
                instance_type="t3.micro",
                region="us-east-1",
                ami_id="ami-12345"
            )
            
            result = ec2_validator.execute(input_data)
            
            assert result.success is True
            # Should have AMI finding
            ami_findings = [f for f in result.findings if 'ECS-optimized' in f.title]
            assert len(ami_findings) == 1
            assert ami_findings[0].severity == Severity.LOW


def test_execute_with_dict_input(ec2_validator, mock_ec2_client):
    """Test execution with dict input instead of Pydantic model"""
    mock_ec2_client.describe_instance_types.return_value = {
        'InstanceTypes': [{'InstanceType': 't3.micro'}]
    }
    
    with patch.object(ec2_validator.session, 'client', return_value=mock_ec2_client):
        input_data = {
            "instance_type": "t3.micro",
            "region": "us-east-1"
        }
        
        result = ec2_validator.execute(input_data)
        
        assert result.success is True


def test_get_instance_type_recommendation(ec2_validator):
    """Test instance type recommendation logic"""
    # Test t2 to t3 recommendation
    rec = ec2_validator._get_instance_type_recommendation("t2.micro", "us-east-1")
    assert "t3.micro" in rec
    
    # Test m4 to m5 recommendation
    rec = ec2_validator._get_instance_type_recommendation("m4.large", "us-west-2")
    assert "m5.large" in rec
    
    # Test unknown family defaults to t3
    rec = ec2_validator._get_instance_type_recommendation("x1.xlarge", "eu-west-1")
    assert "t3.xlarge" in rec


def test_validate_ami_not_found(ec2_validator, mock_ec2_client):
    """Test AMI validation when AMI is not in ECS releases"""
    mock_ec2_client.describe_instance_types.return_value = {
        'InstanceTypes': [{'InstanceType': 't3.micro'}]
    }
    
    # Mock empty AMI releases
    mock_ami_validator = Mock()
    mock_ami_validator.execute.return_value = []
    
    with patch.object(ec2_validator.session, 'client', return_value=mock_ec2_client):
        with patch.object(type(ec2_validator), 'ami_validator', new_callable=lambda: property(lambda self: mock_ami_validator)):
            input_data = EC2ValidatorInput(
                instance_type="t3.micro",
                region="us-east-1",
                ami_id="ami-unknown"
            )
            
            result = ec2_validator.execute(input_data)
            
            assert result.success is True
            # No findings for non-ECS AMI


def test_execute_with_api_error(ec2_validator, mock_ec2_client):
    """Test execution when AWS API returns error"""
    error_response = {
        'Error': {
            'Code': 'UnauthorizedOperation',
            'Message': 'Not authorized'
        }
    }
    mock_ec2_client.describe_instance_types.side_effect = ClientError(
        error_response, 'DescribeInstanceTypes'
    )
    
    with patch.object(ec2_validator.session, 'client', return_value=mock_ec2_client):
        input_data = EC2ValidatorInput(
            instance_type="t3.micro",
            region="us-east-1"
        )
        
        result = ec2_validator.execute(input_data)
        
        assert result.success is True
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.severity == Severity.MEDIUM


def test_execute_with_exception(ec2_validator):
    """Test execution when unexpected exception occurs"""
    with patch.object(ec2_validator.session, 'client', side_effect=Exception("Unexpected error")):
        input_data = EC2ValidatorInput(
            instance_type="t3.micro",
            region="us-east-1"
        )
        
        result = ec2_validator.execute(input_data)
        
        assert result.success is False
        assert result.error is not None
        assert "Unexpected error" in result.error


def test_validate_ami_with_exception(ec2_validator, mock_ec2_client):
    """Test AMI validation when exception occurs"""
    mock_ec2_client.describe_instance_types.return_value = {
        'InstanceTypes': [{'InstanceType': 't3.micro'}]
    }
    
    mock_ami_validator = Mock()
    mock_ami_validator.execute.side_effect = Exception("AMI error")
    
    with patch.object(ec2_validator.session, 'client', return_value=mock_ec2_client):
        with patch.object(type(ec2_validator), 'ami_validator', new_callable=lambda: property(lambda self: mock_ami_validator)):
            input_data = EC2ValidatorInput(
                instance_type="t3.micro",
                region="us-east-1",
                ami_id="ami-12345"
            )
            
            result = ec2_validator.execute(input_data)
            
            # Should still succeed but with AMI error finding
            assert result.success is True
            ami_findings = [f for f in result.findings if 'Unable to retrieve' in f.title]
            assert len(ami_findings) == 1
