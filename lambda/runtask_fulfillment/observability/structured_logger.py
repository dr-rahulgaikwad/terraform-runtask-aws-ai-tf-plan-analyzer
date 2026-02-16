"""Structured JSON logger for Run Task observability."""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class StructuredLogger:
    """Provides structured JSON logging for Run Task operations.
    
    This class emits structured JSON log entries with correlation IDs
    for tracking Run Task executions and tool operations across the system.
    """

    def __init__(self, correlation_id: Optional[str] = None):
        """Initialize the StructuredLogger.
        
        Args:
            correlation_id: Optional correlation ID for tracking related log entries.
                          If not provided, a new UUID will be generated.
        """
        self.correlation_id = correlation_id or str(uuid.uuid4())
        logger.info(f"StructuredLogger initialized with correlation_id: {self.correlation_id}")

    def _log_structured(self, event_type: str, **kwargs: Any) -> None:
        """Log a structured JSON event.
        
        Args:
            event_type: Type of event being logged (e.g., "run_task_execution", "tool_execution")
            **kwargs: Additional fields to include in the log entry
        """
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": self.correlation_id,
            "event_type": event_type,
            **kwargs
        }
        
        # Log as JSON string for structured logging systems
        logger.info(json.dumps(log_entry))

    def log_run_task(
        self,
        run_id: str,
        organization: str,
        workspace: str,
        stage: Optional[str] = None,
        **additional_fields: Any
    ) -> None:
        """Log a Run Task execution event.
        
        Args:
            run_id: HCP Terraform run ID
            organization: HCP Terraform organization name
            workspace: HCP Terraform workspace name
            stage: Optional run stage (e.g., "post_plan", "pre_apply")
            **additional_fields: Additional fields to include in the log entry
        """
        self._log_structured(
            event_type="run_task_execution",
            run_id=run_id,
            organization=organization,
            workspace=workspace,
            stage=stage,
            **additional_fields
        )

    def log_tool_execution(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float,
        error: Optional[str] = None,
        **additional_fields: Any
    ) -> None:
        """Log a tool execution event.
        
        Args:
            tool_name: Name of the tool that was executed
            success: Whether the tool execution succeeded
            duration_ms: Duration of the tool execution in milliseconds
            error: Optional error message if the tool execution failed
            **additional_fields: Additional fields to include in the log entry
        """
        self._log_structured(
            event_type="tool_execution",
            tool_name=tool_name,
            success=success,
            duration_ms=duration_ms,
            error=error,
            **additional_fields
        )

    def log_bedrock_invocation(
        self,
        model_id: str,
        duration_ms: float,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        **additional_fields: Any
    ) -> None:
        """Log a Bedrock model invocation event.
        
        Args:
            model_id: Bedrock model identifier
            duration_ms: Duration of the invocation in milliseconds
            input_tokens: Optional number of input tokens
            output_tokens: Optional number of output tokens
            **additional_fields: Additional fields to include in the log entry
        """
        self._log_structured(
            event_type="bedrock_invocation",
            model_id=model_id,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            **additional_fields
        )

    def log_guardrail_violation(
        self,
        guardrail_id: str,
        action: str,
        topic: Optional[str] = None,
        **additional_fields: Any
    ) -> None:
        """Log a guardrail violation event.
        
        Args:
            guardrail_id: Bedrock guardrail identifier
            action: Action taken by the guardrail (e.g., "BLOCKED", "INTERVENED")
            topic: Optional topic that triggered the guardrail
            **additional_fields: Additional fields to include in the log entry
        """
        self._log_structured(
            event_type="guardrail_violation",
            guardrail_id=guardrail_id,
            action=action,
            topic=topic,
            **additional_fields
        )

    def log_error(
        self,
        error_type: str,
        error_message: str,
        **additional_fields: Any
    ) -> None:
        """Log an error event.
        
        Args:
            error_type: Type of error (e.g., "APIError", "ValidationError", "TimeoutError")
            error_message: Error message
            **additional_fields: Additional fields to include in the log entry
        """
        self._log_structured(
            event_type="error",
            error_type=error_type,
            error_message=error_message,
            **additional_fields
        )

    def get_correlation_id(self) -> str:
        """Get the correlation ID for this logger instance.
        
        Returns:
            The correlation ID string
        """
        return self.correlation_id

    def create_child_logger(self) -> "StructuredLogger":
        """Create a child logger with the same correlation ID.
        
        This is useful for passing the logger to sub-components while
        maintaining the same correlation ID for tracking.
        
        Returns:
            A new StructuredLogger instance with the same correlation ID
        """
        return StructuredLogger(correlation_id=self.correlation_id)
