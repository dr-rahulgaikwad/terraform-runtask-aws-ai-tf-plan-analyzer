"""CloudWatch metrics emitter for Run Task observability."""

import logging
from typing import Optional, Dict, Any
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class MetricsEmitter:
    """Emits CloudWatch metrics for Run Task operations.
    
    This class provides methods to emit duration and count metrics to CloudWatch
    for monitoring Run Task execution and tool performance.
    """

    def __init__(self, namespace: str = "TerraformRunTask", region: Optional[str] = None):
        """Initialize the MetricsEmitter.
        
        Args:
            namespace: CloudWatch namespace for metrics (default: "TerraformRunTask")
            region: AWS region for CloudWatch client (default: None, uses default region)
        """
        self.namespace = namespace
        try:
            self.cloudwatch = boto3.client('cloudwatch', region_name=region)
            logger.info(f"MetricsEmitter initialized with namespace: {namespace}")
        except Exception as e:
            logger.error(f"Failed to initialize CloudWatch client: {e}")
            self.cloudwatch = None

    def emit_duration(
        self,
        metric_name: str,
        duration_ms: float,
        dimensions: Optional[Dict[str, str]] = None
    ) -> None:
        """Emit a duration metric to CloudWatch.
        
        Args:
            metric_name: Name of the metric (e.g., "RunTaskDuration", "ToolExecutionDuration")
            duration_ms: Duration in milliseconds
            dimensions: Optional dimensions for the metric (e.g., {"ToolName": "EC2Validator"})
        """
        if not self.cloudwatch:
            logger.warning(f"CloudWatch client not available, skipping metric: {metric_name}")
            return

        try:
            metric_data = {
                'MetricName': metric_name,
                'Value': duration_ms,
                'Unit': 'Milliseconds'
            }

            if dimensions:
                metric_data['Dimensions'] = [
                    {'Name': key, 'Value': value}
                    for key, value in dimensions.items()
                ]

            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=[metric_data]
            )

        except ClientError as e:
            logger.error(f"Failed to emit duration metric {metric_name}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error emitting duration metric {metric_name}: {e}")

    def emit_count(
        self,
        metric_name: str,
        value: int = 1,
        dimensions: Optional[Dict[str, str]] = None
    ) -> None:
        """Emit a count metric to CloudWatch.
        
        Args:
            metric_name: Name of the metric (e.g., "ToolExecutionSuccess", "ToolExecutionFailure")
            value: Count value (default: 1)
            dimensions: Optional dimensions for the metric (e.g., {"ToolName": "S3Validator", "Status": "Success"})
        """
        if not self.cloudwatch:
            logger.warning(f"CloudWatch client not available, skipping metric: {metric_name}")
            return

        try:
            metric_data = {
                'MetricName': metric_name,
                'Value': value,
                'Unit': 'Count'
            }

            if dimensions:
                metric_data['Dimensions'] = [
                    {'Name': key, 'Value': value}
                    for key, value in dimensions.items()
                ]

            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=[metric_data]
            )

        except ClientError as e:
            logger.error(f"Failed to emit count metric {metric_name}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error emitting count metric {metric_name}: {e}")

    def emit_tool_execution(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float
    ) -> None:
        """Emit metrics for a tool execution.
        
        This is a convenience method that emits both success/failure count
        and duration metrics for a tool execution.
        
        Args:
            tool_name: Name of the tool that was executed
            success: Whether the tool execution succeeded
            duration_ms: Duration of the tool execution in milliseconds
        """
        dimensions = {'ToolName': tool_name}
        
        # Emit success or failure count
        if success:
            self.emit_count('ToolExecutionSuccess', value=1, dimensions=dimensions)
        else:
            self.emit_count('ToolExecutionFailure', value=1, dimensions=dimensions)
        
        # Emit duration metric
        self.emit_duration('ToolExecutionDuration', duration_ms, dimensions=dimensions)
