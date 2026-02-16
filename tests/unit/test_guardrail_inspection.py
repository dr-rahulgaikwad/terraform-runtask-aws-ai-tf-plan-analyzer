"""
Unit tests for guardrail inspection logic in ai.py.

Tests cover:
- Infrastructure-specific guardrail violations
- Content policy violations
- Sensitive information detection
- Logging with full context
- Recommendation generation
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add lambda directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lambda" / "runtask_fulfillment"))

# Mock the bedrock_client before importing ai module
sys.modules['boto3'] = MagicMock()
sys.modules['botocore'] = MagicMock()
sys.modules['botocore.config'] = MagicMock()

# Mock runtask_utils
sys.modules['runtask_utils'] = MagicMock()

# Mock tools
sys.modules['tools.get_ami_releases'] = MagicMock()

# Mock utils
sys.modules['utils'] = MagicMock()

# Now import the module
import ai


@pytest.fixture
def mock_bedrock_client():
    """Mock Bedrock client for testing"""
    return Mock()


@pytest.fixture
def mock_logger():
    """Mock logger for testing"""
    return Mock()


def test_get_guardrail_recommendation_public_s3():
    """Test recommendation for public S3 bucket violation"""
    recommendation = ai._get_guardrail_recommendation("PublicS3Buckets")
    
    assert "Block Public Access" in recommendation
    assert "bucket policies" in recommendation


def test_get_guardrail_recommendation_unencrypted_storage():
    """Test recommendation for unencrypted storage violation"""
    recommendation = ai._get_guardrail_recommendation("UnencryptedStorage")
    
    assert "encryption" in recommendation
    assert "KMS" in recommendation or "AES-256" in recommendation


def test_get_guardrail_recommendation_overly_permissive_iam():
    """Test recommendation for overly permissive IAM violation"""
    recommendation = ai._get_guardrail_recommendation("OverlyPermissiveIAM")
    
    assert "least privilege" in recommendation
    assert "wildcards" in recommendation


def test_get_guardrail_recommendation_unknown_violation():
    """Test recommendation for unknown violation type"""
    recommendation = ai._get_guardrail_recommendation("UnknownViolationType")
    
    assert "security best practices" in recommendation


@patch.object(ai, 'bedrock_client')
@patch.object(ai, 'logger')
@patch.object(ai, 'guardrail_id', 'test-guardrail-id')
@patch.object(ai, 'guardrail_version', '1')
def test_guardrail_inspection_infrastructure_violation(mock_logger, mock_bedrock_client):
    """Test guardrail inspection with infrastructure-specific violation"""
    # Mock Bedrock response with topic policy violation
    mock_bedrock_client.apply_guardrail.return_value = {
        "action": "GUARDRAIL_INTERVENED",
        "outputs": [{"text": "Output blocked due to policy violation"}],
        "assessments": [
            {
                "topicPolicy": {
                    "topics": [
                        {
                            "name": "PublicS3Buckets",
                            "action": "BLOCKED"
                        }
                    ]
                }
            }
        ]
    }
    
    status, response = ai.guardrail_inspection("Make this S3 bucket public")
    
    assert status is False
    assert "blocked" in response.lower()
    
    # Verify warning was logged with full context
    mock_logger.warning.assert_called()
    warning_call = mock_logger.warning.call_args
    assert "Infrastructure guardrail violation detected" in warning_call[0][0]
    assert warning_call[1]["extra"]["violation_type"] == "PublicS3Buckets"
    assert "Block Public Access" in warning_call[1]["extra"]["recommendation"]


@patch.object(ai, 'bedrock_client')
@patch.object(ai, 'logger')
@patch.object(ai, 'guardrail_id', 'test-guardrail-id')
@patch.object(ai, 'guardrail_version', '1')
def test_guardrail_inspection_content_policy_violation(mock_logger, mock_bedrock_client):
    """Test guardrail inspection with content policy violation"""
    # Mock Bedrock response with content policy violation
    mock_bedrock_client.apply_guardrail.return_value = {
        "action": "GUARDRAIL_INTERVENED",
        "outputs": [{"text": "Output blocked due to content policy"}],
        "assessments": [
            {
                "contentPolicy": {
                    "filters": [
                        {
                            "type": "HATE",
                            "action": "BLOCKED",
                            "confidence": "HIGH"
                        }
                    ]
                }
            }
        ]
    }
    
    status, response = ai.guardrail_inspection("Test content")
    
    assert status is False
    
    # Verify warning was logged
    mock_logger.warning.assert_called()
    warning_call = mock_logger.warning.call_args
    assert "Content policy violation detected" in warning_call[0][0]
    assert warning_call[1]["extra"]["filter_type"] == "HATE"


@patch.object(ai, 'bedrock_client')
@patch.object(ai, 'logger')
@patch.object(ai, 'guardrail_id', 'test-guardrail-id')
@patch.object(ai, 'guardrail_version', '1')
def test_guardrail_inspection_sensitive_information(mock_logger, mock_bedrock_client):
    """Test guardrail inspection with sensitive information detection"""
    # Mock Bedrock response with PII detection
    mock_bedrock_client.apply_guardrail.return_value = {
        "action": "GUARDRAIL_INTERVENED",
        "outputs": [{"text": "Output blocked due to sensitive information"}],
        "assessments": [
            {
                "sensitiveInformationPolicy": {
                    "piiEntities": [
                        {
                            "type": "AWS_ACCESS_KEY",
                            "action": "BLOCKED"
                        }
                    ]
                }
            }
        ]
    }
    
    status, response = ai.guardrail_inspection("AKIAIOSFODNN7EXAMPLE")
    
    assert status is False
    
    # Verify warning was logged
    mock_logger.warning.assert_called()
    warning_call = mock_logger.warning.call_args
    assert "Sensitive information detected" in warning_call[0][0]
    assert warning_call[1]["extra"]["entity_type"] == "AWS_ACCESS_KEY"


@patch.object(ai, 'bedrock_client')
@patch.object(ai, 'logger')
@patch.object(ai, 'guardrail_id', 'test-guardrail-id')
@patch.object(ai, 'guardrail_version', '1')
def test_guardrail_inspection_no_violation(mock_logger, mock_bedrock_client):
    """Test guardrail inspection with no violations"""
    # Mock Bedrock response with no violations
    mock_bedrock_client.apply_guardrail.return_value = {
        "action": "NONE",
        "assessments": []
    }
    
    status, response = ai.guardrail_inspection("Safe content")
    
    assert status is True
    assert "No Guardrail action required" in response


@patch.object(ai, 'bedrock_client')
@patch.object(ai, 'logger')
@patch.object(ai, 'guardrail_id', None)
@patch.object(ai, 'guardrail_version', None)
def test_guardrail_inspection_disabled(mock_logger, mock_bedrock_client):
    """Test guardrail inspection when guardrail is not configured"""
    status, response = ai.guardrail_inspection("Any content")
    
    assert status is True
    assert "Guardrail inspection skipped" in response
    
    # Bedrock should not be called
    mock_bedrock_client.apply_guardrail.assert_not_called()


@patch.object(ai, 'bedrock_client')
@patch.object(ai, 'logger')
@patch.object(ai, 'guardrail_id', 'test-guardrail-id')
@patch.object(ai, 'guardrail_version', '1')
def test_guardrail_inspection_multiple_violations(mock_logger, mock_bedrock_client):
    """Test guardrail inspection with multiple violation types"""
    # Mock Bedrock response with multiple violations
    mock_bedrock_client.apply_guardrail.return_value = {
        "action": "GUARDRAIL_INTERVENED",
        "outputs": [{"text": "Output blocked due to multiple violations"}],
        "assessments": [
            {
                "topicPolicy": {
                    "topics": [
                        {
                            "name": "PublicS3Buckets",
                            "action": "BLOCKED"
                        },
                        {
                            "name": "UnencryptedStorage",
                            "action": "BLOCKED"
                        }
                    ]
                },
                "contentPolicy": {
                    "filters": [
                        {
                            "type": "MISCONDUCT",
                            "action": "BLOCKED",
                            "confidence": "MEDIUM"
                        }
                    ]
                }
            }
        ]
    }
    
    status, response = ai.guardrail_inspection("Test content with multiple issues")
    
    assert status is False
    
    # Verify multiple warnings were logged
    assert mock_logger.warning.call_count >= 3


@patch.object(ai, 'bedrock_client')
@patch.object(ai, 'logger')
@patch.object(ai, 'guardrail_id', 'test-guardrail-id')
@patch.object(ai, 'guardrail_version', '1')
def test_guardrail_inspection_input_mode(mock_logger, mock_bedrock_client):
    """Test guardrail inspection with INPUT mode"""
    mock_bedrock_client.apply_guardrail.return_value = {
        "action": "NONE",
        "assessments": []
    }
    
    status, response = ai.guardrail_inspection("Test content", input_mode='INPUT')
    
    # Verify INPUT mode was passed to Bedrock
    call_args = mock_bedrock_client.apply_guardrail.call_args
    assert call_args[1]["source"] == "INPUT"
