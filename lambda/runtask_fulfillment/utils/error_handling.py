"""
Error handling utilities for Terraform Run Task fulfillment.

Provides retry logic with exponential backoff and graceful degradation
for tool execution failures.
"""

import logging
import time
from typing import Callable, Any, List, TypeVar, Optional
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RetryableError(Exception):
    """Base exception for errors that should trigger retry logic."""
    pass


def is_retryable_error(error: Exception) -> bool:
    """
    Classify if an error is retryable (throttling, network errors).
    
    Args:
        error: The exception to classify
        
    Returns:
        True if the error should trigger a retry, False otherwise
    """
    # Check for boto3 ClientError with retryable error codes
    if isinstance(error, ClientError):
        error_code = error.response.get('Error', {}).get('Code', '')
        retryable_codes = [
            'ThrottlingException',
            'Throttling',
            'TooManyRequestsException',
            'ProvisionedThroughputExceededException',
            'RequestLimitExceeded',
            'ServiceUnavailable',
            'InternalError',
            'RequestTimeout',
        ]
        if error_code in retryable_codes:
            return True
    
    # Check for common network/timeout errors
    error_message = str(error).lower()
    retryable_patterns = [
        'timeout',
        'timed out',
        'connection',
        'network',
        'temporarily unavailable',
    ]
    
    return any(pattern in error_message for pattern in retryable_patterns)


def retry_with_backoff(
    func: Callable[[], T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    retryable_check: Optional[Callable[[Exception], bool]] = None
) -> T:
    """
    Retry a function with exponential backoff.
    
    Implements exponential backoff with delays of 1s, 2s, 4s for retry attempts.
    Only retries on errors classified as retryable (throttling, network errors).
    
    Args:
        func: The function to execute (should take no arguments)
        max_retries: Maximum number of retry attempts (default: 3)
        initial_delay: Initial delay in seconds (default: 1.0)
        backoff_factor: Multiplier for delay on each retry (default: 2.0)
        retryable_check: Optional custom function to check if error is retryable
        
    Returns:
        The result of the function call
        
    Raises:
        The last exception if all retries are exhausted
        
    Example:
        >>> result = retry_with_backoff(lambda: bedrock_client.converse(...))
    """
    if retryable_check is None:
        retryable_check = is_retryable_error
    
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_exception = e
            
            # Check if this error should trigger a retry
            if not retryable_check(e):
                logger.warning(f"Non-retryable error encountered: {type(e).__name__}: {e}")
                raise
            
            # If this was the last attempt, raise the exception
            if attempt == max_retries - 1:
                logger.error(f"All {max_retries} retry attempts exhausted for {func.__name__}")
                raise
            
            # Calculate delay with exponential backoff
            delay = initial_delay * (backoff_factor ** attempt)
            logger.warning(
                f"Retryable error on attempt {attempt + 1}/{max_retries}: "
                f"{type(e).__name__}: {e}. Retrying in {delay}s..."
            )
            time.sleep(delay)
    
    # This should never be reached, but just in case
    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected state in retry_with_backoff")


def execute_tools_with_degradation(
    tools: List[Any],
    execute_func: Callable[[Any], Any]
) -> List[Any]:
    """
    Execute tools with graceful degradation.
    
    Continues analysis when individual tools fail, returning partial results
    with error details for failed tools. Logs tool failures without stopping
    execution.
    
    Args:
        tools: List of tools to execute
        execute_func: Function that executes a single tool and returns a result
        
    Returns:
        List of results (successful or error results) for each tool
        
    Example:
        >>> results = execute_tools_with_degradation(
        ...     tools=[ec2_tool, s3_tool, sg_tool],
        ...     execute_func=lambda tool: tool.execute(plan_data)
        ... )
    """
    results = []
    
    for tool in tools:
        tool_name = getattr(tool, 'name', str(tool))
        
        try:
            logger.info(f"Executing tool: {tool_name}")
            result = execute_func(tool)
            results.append(result)
            logger.info(f"Tool {tool_name} executed successfully")
            
        except Exception as e:
            logger.error(
                f"Tool {tool_name} failed: {type(e).__name__}: {e}",
                exc_info=True
            )
            
            # Create an error result object
            # The structure depends on what the tool normally returns
            # This is a generic approach that can be adapted
            error_result = {
                'tool_name': tool_name,
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__,
                'findings': []
            }
            results.append(error_result)
    
    # Log summary
    successful = sum(1 for r in results if isinstance(r, dict) and r.get('success', True))
    failed = len(results) - successful
    logger.info(f"Tool execution complete: {successful} successful, {failed} failed")
    
    return results
