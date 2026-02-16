"""
Unit tests for MetricsEmitter class.

Tests cover:
- Duration metric emission
- Count metric emission
- Tool execution metrics
- Error handling when CloudWatch is unavailable
- Metric dimensions
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from botocore.exceptions import ClientError

# Add lambda directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lambda" / "runtask_fulfillment"))

from observability.metrics_emitter import MetricsEmitter


@pytest.fixture
def mock_cloudwatch():
    """Create a mock CloudWatch client"""
    with patch('boto3.client') as mock_client:
        mock_cw = Mock()
        mock_client.return_value = mock_cw
        yield mock_cw


def test_metrics_emitter_initialization(mock_cloudwatch):
    """Test MetricsEmitter initializes correctly"""
    emitter = MetricsEmitter(namespace="TestNamespace", region="us-east-1")
    
    assert emitter.namespace == "TestNamespace"
    assert emitter.cloudwatch is not None


def test_metrics_emitter_initialization_default_namespace(mock_cloudwatch):
    """Test MetricsEmitter uses default namespace"""
    emitter = MetricsEmitter()
    
    assert emitter.namespace == "TerraformRunTask"


def test_emit_duration_basic(mock_cloudwatch):
    """Test emitting a basic duration metric"""
    emitter = MetricsEmitter()
    
    emitter.emit_duration("TestDuration", 123.45)
    
    mock_cloudwatch.put_metric_data.assert_called_once()
    call_args = mock_cloudwatch.put_metric_data.call_args
    
    assert call_args[1]['Namespace'] == "TerraformRunTask"
    assert len(call_args[1]['MetricData']) == 1
    
    metric = call_args[1]['MetricData'][0]
    assert metric['MetricName'] == "TestDuration"
    assert metric['Value'] == 123.45
    assert metric['Unit'] == 'Milliseconds'


def test_emit_duration_with_dimensions(mock_cloudwatch):
    """Test emitting duration metric with dimensions"""
    emitter = MetricsEmitter()
    
    dimensions = {'ToolName': 'EC2Validator', 'Status': 'Success'}
    emitter.emit_duration("ToolExecutionDuration", 250.0, dimensions=dimensions)
    
    call_args = mock_cloudwatch.put_metric_data.call_args
    metric = call_args[1]['MetricData'][0]
    
    assert 'Dimensions' in metric
    assert len(metric['Dimensions']) == 2
    
    dim_dict = {d['Name']: d['Value'] for d in metric['Dimensions']}
    assert dim_dict['ToolName'] == 'EC2Validator'
    assert dim_dict['Status'] == 'Success'


def test_emit_count_basic(mock_cloudwatch):
    """Test emitting a basic count metric"""
    emitter = MetricsEmitter()
    
    emitter.emit_count("TestCount", value=5)
    
    mock_cloudwatch.put_metric_data.assert_called_once()
    call_args = mock_cloudwatch.put_metric_data.call_args
    
    metric = call_args[1]['MetricData'][0]
    assert metric['MetricName'] == "TestCount"
    assert metric['Value'] == 5
    assert metric['Unit'] == 'Count'


def test_emit_count_default_value(mock_cloudwatch):
    """Test emitting count metric with default value of 1"""
    emitter = MetricsEmitter()
    
    emitter.emit_count("TestCount")
    
    call_args = mock_cloudwatch.put_metric_data.call_args
    metric = call_args[1]['MetricData'][0]
    
    assert metric['Value'] == 1


def test_emit_count_with_dimensions(mock_cloudwatch):
    """Test emitting count metric with dimensions"""
    emitter = MetricsEmitter()
    
    dimensions = {'ToolName': 'S3Validator'}
    emitter.emit_count("ToolExecutionSuccess", value=1, dimensions=dimensions)
    
    call_args = mock_cloudwatch.put_metric_data.call_args
    metric = call_args[1]['MetricData'][0]
    
    assert 'Dimensions' in metric
    assert len(metric['Dimensions']) == 1
    assert metric['Dimensions'][0]['Name'] == 'ToolName'
    assert metric['Dimensions'][0]['Value'] == 'S3Validator'


def test_emit_tool_execution_success(mock_cloudwatch):
    """Test emitting metrics for successful tool execution"""
    emitter = MetricsEmitter()
    
    emitter.emit_tool_execution("EC2Validator", success=True, duration_ms=150.0)
    
    # Should emit 2 metrics: success count and duration
    assert mock_cloudwatch.put_metric_data.call_count == 2
    
    # Check first call (success count)
    first_call = mock_cloudwatch.put_metric_data.call_args_list[0]
    success_metric = first_call[1]['MetricData'][0]
    assert success_metric['MetricName'] == 'ToolExecutionSuccess'
    assert success_metric['Value'] == 1
    
    # Check second call (duration)
    second_call = mock_cloudwatch.put_metric_data.call_args_list[1]
    duration_metric = second_call[1]['MetricData'][0]
    assert duration_metric['MetricName'] == 'ToolExecutionDuration'
    assert duration_metric['Value'] == 150.0


def test_emit_tool_execution_failure(mock_cloudwatch):
    """Test emitting metrics for failed tool execution"""
    emitter = MetricsEmitter()
    
    emitter.emit_tool_execution("S3Validator", success=False, duration_ms=75.0)
    
    # Should emit 2 metrics: failure count and duration
    assert mock_cloudwatch.put_metric_data.call_count == 2
    
    # Check first call (failure count)
    first_call = mock_cloudwatch.put_metric_data.call_args_list[0]
    failure_metric = first_call[1]['MetricData'][0]
    assert failure_metric['MetricName'] == 'ToolExecutionFailure'
    assert failure_metric['Value'] == 1


def test_emit_duration_cloudwatch_unavailable():
    """Test emitting duration metric when CloudWatch client is unavailable"""
    with patch('boto3.client') as mock_client:
        mock_client.side_effect = Exception("CloudWatch unavailable")
        
        emitter = MetricsEmitter()
        
        # Should not raise exception
        emitter.emit_duration("TestDuration", 100.0)
        
        # CloudWatch client should be None
        assert emitter.cloudwatch is None


def test_emit_count_cloudwatch_unavailable():
    """Test emitting count metric when CloudWatch client is unavailable"""
    with patch('boto3.client') as mock_client:
        mock_client.side_effect = Exception("CloudWatch unavailable")
        
        emitter = MetricsEmitter()
        
        # Should not raise exception
        emitter.emit_count("TestCount", value=1)
        
        # CloudWatch client should be None
        assert emitter.cloudwatch is None


def test_emit_duration_client_error(mock_cloudwatch):
    """Test handling ClientError when emitting duration metric"""
    emitter = MetricsEmitter()
    
    # Simulate ClientError
    mock_cloudwatch.put_metric_data.side_effect = ClientError(
        {'Error': {'Code': 'ThrottlingException', 'Message': 'Rate exceeded'}},
        'PutMetricData'
    )
    
    # Should not raise exception
    emitter.emit_duration("TestDuration", 100.0)


def test_emit_count_client_error(mock_cloudwatch):
    """Test handling ClientError when emitting count metric"""
    emitter = MetricsEmitter()
    
    # Simulate ClientError
    mock_cloudwatch.put_metric_data.side_effect = ClientError(
        {'Error': {'Code': 'InvalidParameterValue', 'Message': 'Invalid metric'}},
        'PutMetricData'
    )
    
    # Should not raise exception
    emitter.emit_count("TestCount", value=1)


def test_emit_duration_unexpected_error(mock_cloudwatch):
    """Test handling unexpected error when emitting duration metric"""
    emitter = MetricsEmitter()
    
    # Simulate unexpected error
    mock_cloudwatch.put_metric_data.side_effect = RuntimeError("Unexpected error")
    
    # Should not raise exception
    emitter.emit_duration("TestDuration", 100.0)


def test_emit_count_unexpected_error(mock_cloudwatch):
    """Test handling unexpected error when emitting count metric"""
    emitter = MetricsEmitter()
    
    # Simulate unexpected error
    mock_cloudwatch.put_metric_data.side_effect = ValueError("Invalid value")
    
    # Should not raise exception
    emitter.emit_count("TestCount", value=1)


def test_multiple_dimensions(mock_cloudwatch):
    """Test emitting metric with multiple dimensions"""
    emitter = MetricsEmitter()
    
    dimensions = {
        'ToolName': 'CostEstimator',
        'Status': 'Success',
        'Region': 'us-east-1'
    }
    
    emitter.emit_duration("ToolExecutionDuration", 300.0, dimensions=dimensions)
    
    call_args = mock_cloudwatch.put_metric_data.call_args
    metric = call_args[1]['MetricData'][0]
    
    assert len(metric['Dimensions']) == 3
    dim_dict = {d['Name']: d['Value'] for d in metric['Dimensions']}
    assert dim_dict['ToolName'] == 'CostEstimator'
    assert dim_dict['Status'] == 'Success'
    assert dim_dict['Region'] == 'us-east-1'


def test_custom_namespace(mock_cloudwatch):
    """Test using custom namespace"""
    emitter = MetricsEmitter(namespace="CustomNamespace")
    
    emitter.emit_count("TestMetric", value=1)
    
    call_args = mock_cloudwatch.put_metric_data.call_args
    assert call_args[1]['Namespace'] == "CustomNamespace"


def test_emit_run_task_duration(mock_cloudwatch):
    """Test emitting RunTaskDuration metric as specified in requirements"""
    emitter = MetricsEmitter()
    
    emitter.emit_duration("RunTaskDuration", 5000.0)
    
    call_args = mock_cloudwatch.put_metric_data.call_args
    metric = call_args[1]['MetricData'][0]
    
    assert metric['MetricName'] == "RunTaskDuration"
    assert metric['Value'] == 5000.0
    assert metric['Unit'] == 'Milliseconds'


def test_emit_tool_execution_success_metric(mock_cloudwatch):
    """Test emitting ToolExecutionSuccess metric as specified in requirements"""
    emitter = MetricsEmitter()
    
    dimensions = {'ToolName': 'SecurityGroupValidator'}
    emitter.emit_count("ToolExecutionSuccess", value=1, dimensions=dimensions)
    
    call_args = mock_cloudwatch.put_metric_data.call_args
    metric = call_args[1]['MetricData'][0]
    
    assert metric['MetricName'] == "ToolExecutionSuccess"
    assert metric['Value'] == 1


def test_emit_tool_execution_failure_metric(mock_cloudwatch):
    """Test emitting ToolExecutionFailure metric as specified in requirements"""
    emitter = MetricsEmitter()
    
    dimensions = {'ToolName': 'EC2Validator'}
    emitter.emit_count("ToolExecutionFailure", value=1, dimensions=dimensions)
    
    call_args = mock_cloudwatch.put_metric_data.call_args
    metric = call_args[1]['MetricData'][0]
    
    assert metric['MetricName'] == "ToolExecutionFailure"
    assert metric['Value'] == 1
