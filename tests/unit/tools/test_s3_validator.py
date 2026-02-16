"""
Unit tests for S3ValidatorTool.

Tests cover:
- Public access block validation
- Encryption configuration validation
- Error handling
- Bedrock spec generation
"""

import pytest
from unittest.mock import Mock, patch
import sys
from pathlib import Path

# Add lambda directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "lambda" / "runtask_fulfillment"))

from tools.s3_validator import S3ValidatorTool, S3ValidatorInput
from models.tool_models import ToolOutput, Finding, Severity


@pytest.fixture
def s3_validator():
    """Create S3ValidatorTool instance"""
    return S3ValidatorTool()


def test_tool_properties(s3_validator):
    """Test that tool has required properties"""
    assert s3_validator.name == "S3Validator"
    assert isinstance(s3_validator.description, str)
    assert len(s3_validator.description) > 0
    assert isinstance(s3_validator.input_schema, dict)
    assert "properties" in s3_validator.input_schema


def test_input_schema_structure(s3_validator):
    """Test that input schema has correct structure"""
    schema = s3_validator.input_schema
    
    assert schema["type"] == "object"
    assert "bucket_name" in schema["properties"]
    assert "public_access_block" in schema["properties"]
    assert "encryption" in schema["properties"]
    assert "bucket_name" in schema["required"]


def test_bedrock_spec_format(s3_validator):
    """Test that Bedrock spec has correct format"""
    spec = s3_validator.get_bedrock_spec()
    
    assert "toolSpec" in spec
    assert spec["toolSpec"]["name"] == "S3Validator"
    assert "description" in spec["toolSpec"]
    assert "inputSchema" in spec["toolSpec"]
    assert "json" in spec["toolSpec"]["inputSchema"]


def test_execute_with_all_public_access_blocked(s3_validator):
    """Test execution with all public access block settings enabled"""
    input_data = S3ValidatorInput(
        bucket_name="my-secure-bucket",
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
    
    result = s3_validator.execute(input_data)
    
    assert result.success is True
    assert isinstance(result.findings, list)
    # All settings correct, should have no critical/high findings
    critical_findings = [f for f in result.findings if f.severity in [Severity.CRITICAL, Severity.HIGH]]
    assert len(critical_findings) == 0


def test_execute_with_no_public_access_block(s3_validator):
    """Test execution when public access block is not configured"""
    input_data = S3ValidatorInput(
        bucket_name="my-public-bucket",
        public_access_block=None,
        encryption={
            "sse_algorithm": "AES256"
        }
    )
    
    result = s3_validator.execute(input_data)
    
    assert result.success is True
    assert len(result.findings) >= 1
    
    # Should have critical finding for missing public access block
    public_findings = [f for f in result.findings if "public access block" in f.title.lower()]
    assert len(public_findings) == 1
    assert public_findings[0].severity == Severity.CRITICAL
    assert "my-public-bucket" in public_findings[0].title


def test_execute_with_partial_public_access_block(s3_validator):
    """Test execution with some public access block settings disabled"""
    input_data = S3ValidatorInput(
        bucket_name="my-bucket",
        public_access_block={
            "block_public_acls": True,
            "block_public_policy": False,  # Disabled
            "ignore_public_acls": True,
            "restrict_public_buckets": False  # Disabled
        },
        encryption={
            "sse_algorithm": "AES256"
        }
    )
    
    result = s3_validator.execute(input_data)
    
    assert result.success is True
    
    # Should have critical finding for disabled settings
    public_findings = [f for f in result.findings if "disabled" in f.title.lower()]
    assert len(public_findings) == 1
    assert public_findings[0].severity == Severity.CRITICAL
    assert "Block Public Policy" in public_findings[0].description
    assert "Restrict Public Buckets" in public_findings[0].description


def test_execute_with_no_encryption(s3_validator):
    """Test execution when encryption is not configured"""
    input_data = S3ValidatorInput(
        bucket_name="my-unencrypted-bucket",
        public_access_block={
            "block_public_acls": True,
            "block_public_policy": True,
            "ignore_public_acls": True,
            "restrict_public_buckets": True
        },
        encryption=None
    )
    
    result = s3_validator.execute(input_data)
    
    assert result.success is True
    assert len(result.findings) >= 1
    
    # Should have high severity finding for missing encryption
    encryption_findings = [f for f in result.findings if "encryption" in f.title.lower()]
    assert len(encryption_findings) == 1
    assert encryption_findings[0].severity == Severity.HIGH
    assert "my-unencrypted-bucket" in encryption_findings[0].title


def test_execute_with_aes256_encryption(s3_validator):
    """Test execution with AES256 encryption"""
    input_data = S3ValidatorInput(
        bucket_name="my-bucket",
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
    
    result = s3_validator.execute(input_data)
    
    assert result.success is True
    # Should have no critical/high findings
    critical_findings = [f for f in result.findings if f.severity in [Severity.CRITICAL, Severity.HIGH]]
    assert len(critical_findings) == 0


def test_execute_with_kms_encryption(s3_validator):
    """Test execution with KMS encryption and key ID"""
    input_data = S3ValidatorInput(
        bucket_name="my-bucket",
        public_access_block={
            "block_public_acls": True,
            "block_public_policy": True,
            "ignore_public_acls": True,
            "restrict_public_buckets": True
        },
        encryption={
            "sse_algorithm": "aws:kms",
            "kms_master_key_id": "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012"
        }
    )
    
    result = s3_validator.execute(input_data)
    
    assert result.success is True
    # Should have no critical/high findings
    critical_findings = [f for f in result.findings if f.severity in [Severity.CRITICAL, Severity.HIGH]]
    assert len(critical_findings) == 0


def test_execute_with_kms_encryption_no_key(s3_validator):
    """Test execution with KMS encryption but no key ID specified"""
    input_data = S3ValidatorInput(
        bucket_name="my-bucket",
        public_access_block={
            "block_public_acls": True,
            "block_public_policy": True,
            "ignore_public_acls": True,
            "restrict_public_buckets": True
        },
        encryption={
            "sse_algorithm": "aws:kms"
        }
    )
    
    result = s3_validator.execute(input_data)
    
    assert result.success is True
    
    # Should have low severity finding about default KMS key
    kms_findings = [f for f in result.findings if "default kms key" in f.title.lower()]
    assert len(kms_findings) == 1
    assert kms_findings[0].severity == Severity.LOW


def test_execute_with_invalid_encryption_algorithm(s3_validator):
    """Test execution with unsupported encryption algorithm"""
    input_data = S3ValidatorInput(
        bucket_name="my-bucket",
        public_access_block={
            "block_public_acls": True,
            "block_public_policy": True,
            "ignore_public_acls": True,
            "restrict_public_buckets": True
        },
        encryption={
            "sse_algorithm": "INVALID"
        }
    )
    
    result = s3_validator.execute(input_data)
    
    assert result.success is True
    
    # Should have high severity finding for unsupported algorithm
    encryption_findings = [f for f in result.findings if "unsupported" in f.title.lower()]
    assert len(encryption_findings) == 1
    assert encryption_findings[0].severity == Severity.HIGH


def test_execute_with_missing_encryption_algorithm(s3_validator):
    """Test execution with encryption config but no algorithm"""
    input_data = S3ValidatorInput(
        bucket_name="my-bucket",
        public_access_block={
            "block_public_acls": True,
            "block_public_policy": True,
            "ignore_public_acls": True,
            "restrict_public_buckets": True
        },
        encryption={}
    )
    
    result = s3_validator.execute(input_data)
    
    assert result.success is True
    
    # Should have high severity finding for invalid config
    encryption_findings = [f for f in result.findings if "invalid encryption" in f.title.lower()]
    assert len(encryption_findings) == 1
    assert encryption_findings[0].severity == Severity.HIGH


def test_execute_with_dict_input(s3_validator):
    """Test execution with dict input instead of Pydantic model"""
    input_data = {
        "bucket_name": "my-bucket",
        "public_access_block": {
            "block_public_acls": True,
            "block_public_policy": True,
            "ignore_public_acls": True,
            "restrict_public_buckets": True
        },
        "encryption": {
            "sse_algorithm": "AES256"
        }
    }
    
    result = s3_validator.execute(input_data)
    
    assert result.success is True


def test_execute_with_multiple_issues(s3_validator):
    """Test execution with both public access and encryption issues"""
    input_data = S3ValidatorInput(
        bucket_name="my-insecure-bucket",
        public_access_block=None,
        encryption=None
    )
    
    result = s3_validator.execute(input_data)
    
    assert result.success is True
    assert len(result.findings) >= 2
    
    # Should have findings for both issues
    public_findings = [f for f in result.findings if "public" in f.title.lower()]
    encryption_findings = [f for f in result.findings if "encryption" in f.title.lower()]
    
    assert len(public_findings) >= 1
    assert len(encryption_findings) >= 1
    assert public_findings[0].severity == Severity.CRITICAL
    assert encryption_findings[0].severity == Severity.HIGH


def test_execute_with_case_insensitive_algorithm(s3_validator):
    """Test that encryption algorithm is case-insensitive"""
    # Test uppercase AES256
    input_data = S3ValidatorInput(
        bucket_name="my-bucket",
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
    
    result = s3_validator.execute(input_data)
    assert result.success is True
    
    # Test lowercase aes256
    input_data.encryption["sse_algorithm"] = "aes256"
    result = s3_validator.execute(input_data)
    assert result.success is True


def test_execute_with_exception(s3_validator):
    """Test execution when unexpected exception occurs"""
    # Create invalid input that will cause an exception
    with patch('tools.s3_validator.S3ValidatorInput', side_effect=Exception("Unexpected error")):
        input_data = {
            "bucket_name": "my-bucket"
        }
        
        result = s3_validator.execute(input_data)
        
        assert result.success is False
        assert result.error is not None
        assert "Unexpected error" in result.error


def test_remediation_includes_terraform_code(s3_validator):
    """Test that remediation steps include Terraform code examples"""
    input_data = S3ValidatorInput(
        bucket_name="my-bucket",
        public_access_block=None,
        encryption=None
    )
    
    result = s3_validator.execute(input_data)
    
    # Check that remediation includes Terraform resource blocks
    for finding in result.findings:
        assert "resource" in finding.remediation
        assert "aws_s3_bucket" in finding.remediation or "sse_algorithm" in finding.remediation
