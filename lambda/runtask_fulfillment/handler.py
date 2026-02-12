import json
import logging
import os
import time
import signal

import boto3

import ai
import runtask_utils
from tools.registry import ToolRegistry
from tools.ec2_validator import EC2ValidatorTool
from tools.s3_validator import S3ValidatorTool
from tools.security_group_validator import SecurityGroupValidatorTool
from tools.cost_estimator import CostEstimatorTool
from observability.metrics_emitter import MetricsEmitter
from observability.structured_logger import StructuredLogger
from formatters.output_formatter import OutputFormatter
from utils.error_handling import retry_with_backoff, is_retryable_error

region = os.environ.get("AWS_REGION", None)
dev_mode = os.environ.get("DEV_MODE", "true")
log_level = os.environ.get("log_level", logging.INFO)

logger = logging.getLogger()
logger.setLevel(log_level)

session = boto3.Session()
cwl_client = session.client('logs')

# Initialize global components
tool_registry = ToolRegistry()
metrics_emitter = MetricsEmitter(namespace="TerraformRunTask", region=region)
output_formatter = OutputFormatter()

# Register all validator tools
def initialize_tools():
    """Initialize and register all validator tools."""
    try:
        tool_registry.register(EC2ValidatorTool())
        logger.info("Registered EC2ValidatorTool")
    except Exception as e:
        logger.error(f"Failed to register EC2ValidatorTool: {e}")
    
    try:
        tool_registry.register(S3ValidatorTool())
        logger.info("Registered S3ValidatorTool")
    except Exception as e:
        logger.error(f"Failed to register S3ValidatorTool: {e}")
    
    try:
        tool_registry.register(SecurityGroupValidatorTool())
        logger.info("Registered SecurityGroupValidatorTool")
    except Exception as e:
        logger.error(f"Failed to register SecurityGroupValidatorTool: {e}")
    
    try:
        tool_registry.register(CostEstimatorTool())
        logger.info("Registered CostEstimatorTool")
    except Exception as e:
        logger.error(f"Failed to register CostEstimatorTool: {e}")
    
    logger.info(f"Tool registry initialized with {len(tool_registry.list_tools())} tools: {tool_registry.list_tools()}")

# Initialize tools on module load
initialize_tools()

# Timeout handler for Lambda execution
class TimeoutException(Exception):
    """Exception raised when Lambda is about to timeout."""
    pass

def timeout_handler(signum, frame):
    """Signal handler for Lambda timeout."""
    raise TimeoutException("Lambda execution approaching timeout")

def setup_timeout_handler(context):
    """
    Set up a timeout handler that triggers before Lambda timeout.
    
    Args:
        context: Lambda context object with get_remaining_time_in_millis()
    """
    if context and hasattr(context, 'get_remaining_time_in_millis'):
        # Trigger timeout handler 5 seconds before actual timeout
        remaining_time = context.get_remaining_time_in_millis() / 1000.0
        timeout_buffer = max(5, remaining_time * 0.1)  # 10% buffer or 5s minimum
        signal.alarm(int(remaining_time - timeout_buffer))
        signal.signal(signal.SIGALRM, timeout_handler)

# THIS IS THE MAIN FUNCTION TO IMPLEMENT BUSINESS LOGIC
# TO PROCESS THE TERRAFORM PLAN FILE or TERRAFORM CONFIG (.tar.gz)
# SCHEMA - https://developer.hashicorp.com/terraform/cloud-docs/api-docs/run-tasks/run-tasks-integration#severity-and-status-tags
def process_run_task(type: str, data: str, run_id: str, structured_logger: StructuredLogger):
    url = None
    results = []
    status = "passed"
    message = "Placeholder value"
    partial_results = False
    
    # Start timing for metrics
    start_time = time.time()

    cw_log_group_name = os.environ.get("CW_LOG_GROUP_NAME", None)
    if cw_log_group_name and region:
        lg_name = cw_log_group_name.replace("/", "$252F")
        url = f"https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#logsV2:log-groups/log-group/{lg_name}/log-events/{run_id}"

    try:
        if type == "pre_plan":
            # Process the Terraform config file
            pass

        elif type == "post_plan":
            # Process the Terraform plan file
            
            # Log the run task execution
            structured_logger.log_run_task(
                run_id=run_id,
                organization="unknown",  # Will be populated by lambda_handler
                workspace="unknown",     # Will be populated by lambda_handler
                stage=type
            )
            
            # Execute AI analysis with tool registry
            message, results = ai.eval(data, tool_registry, structured_logger, metrics_emitter)
    
    except TimeoutException as e:
        # Handle Lambda timeout gracefully - return partial results
        logger.warning(f"Lambda execution approaching timeout: {e}")
        structured_logger.log_error(
            error_type="TimeoutWarning",
            error_message="Analysis timed out, returning partial results"
        )
        
        # Return partial results with timeout indicator
        status = "passed"  # Don't block deployment on timeout
        message = "⚠️ Analysis timed out - partial results returned. Check CloudWatch logs for details."
        if not results:
            results = [{
                "type": "task-result-outcomes",
                "attributes": {
                    "outcome-id": "timeout-warning",
                    "description": "Analysis Timeout",
                    "body": "The analysis timed out before completion. This is a transient issue and does not block your deployment.",
                    "url": url
                }
            }]
        partial_results = True
        
    except Exception as e:
        # Check if this is a transient error
        if is_retryable_error(e):
            logger.warning(f"Transient error encountered: {type(e).__name__}: {e}")
            structured_logger.log_error(
                error_type=type(e).__name__,
                error_message=str(e),
                is_transient=True
            )
            
            # Return "passed" status for transient errors to avoid blocking deployments
            status = "passed"
            message = f"⚠️ Transient error occurred: {type(e).__name__}. Analysis skipped but deployment not blocked."
            results = [{
                "type": "task-result-outcomes",
                "attributes": {
                    "outcome-id": "transient-error",
                    "description": "Transient Error",
                    "body": f"A transient error occurred during analysis: {str(e)}\n\nThis does not block your deployment. The issue should resolve automatically.",
                    "url": url
                }
            }]
        else:
            # Non-transient error - re-raise to be handled by caller
            raise
    
    # Emit total run task duration metric
    duration_ms = (time.time() - start_time) * 1000
    metrics_emitter.emit_duration("RunTaskDuration", duration_ms)
    structured_logger.log_run_task(
        run_id=run_id,
        organization="unknown",
        workspace="unknown",
        stage=type,
        duration_ms=duration_ms,
        status=status,
        partial_results=partial_results
    )

    return url, status, message, results

def write_run_task_log(run_id: str, results: list, cw_log_group_dest: str):
    for result in results:
        if result["type"] == "task-result-outcomes":
            runtask_utils.log_helper(
                cwl_client = cwl_client,
                log_group_name = cw_log_group_dest,
                log_stream_name = run_id,
                log_message = result["attributes"]["description"]
            )

            runtask_utils.log_helper(
                cwl_client = cwl_client,
                log_group_name = cw_log_group_dest,
                log_stream_name = run_id,
                log_message = result["attributes"]["body"]
            )

# Main handler for the Lambda function
def lambda_handler(event, context):
    
    # Set up timeout handler to catch approaching Lambda timeout
    try:
        setup_timeout_handler(context)
    except Exception as e:
        logger.warning(f"Could not set up timeout handler: {e}")
    
    # Initialize structured logger with correlation ID from run_id
    run_id = event.get("payload", {}).get("detail", {}).get("run_id", "unknown")
    structured_logger = StructuredLogger(correlation_id=run_id)

    # Initialize the response object
    runtask_response = {
        "url": "",
        "status": "failed",
        "message": "Successful!",
        "results": [],
    }

    try:

        # When a user adds a new run task to their HCP Terraform organization, HCP Terraform will
        # validate the run task address and HMAC by sending a payload with dummy data.
        if event["payload"]["detail"]["access_token"] != "test-token":

            access_token = event["payload"]["detail"]["access_token"]
            organization_name = event["payload"]["detail"]["organization_name"]
            workspace_id = event["payload"]["detail"]["workspace_id"]
            run_id = event["payload"]["detail"]["run_id"]
            task_result_callback_url = event["payload"]["detail"][
                "task_result_callback_url"
            ]
            
            # Update structured logger with organization and workspace info
            structured_logger.log_run_task(
                run_id=run_id,
                organization=organization_name,
                workspace=workspace_id,
                stage=event["payload"]["detail"]["stage"]
            )

            # Segment run tasks based on stage
            if event["payload"]["detail"]["stage"] == "pre_plan":

                # Download the config files locally
                # Docs - https://www.terraform.io/cloud-docs/api-docs/configuration-versions#download-configuration-files
                configuration_version_download_url = event["payload"]["detail"][
                    "configuration_version_download_url"
                ]

                # Download the config to a folder
                config_file = runtask_utils.download_config(
                    configuration_version_download_url, access_token
                )

                # Run the implemented business logic here
                url, status, message, results = process_run_task(
                    type="pre_plan", data=config_file, run_id=run_id, structured_logger=structured_logger
                )

            elif event["payload"]["detail"]["stage"] == "post_plan":

                # Do some processing on the run task event
                # Docs - https://www.terraform.io/cloud-docs/api-docs/run-tasks-integration#request-json
                plan_json_api_url = event["payload"]["detail"]["plan_json_api_url"]

                # Get the plan JSON
                plan_json, error = runtask_utils.get_plan(
                    plan_json_api_url, access_token
                )
                if plan_json:

                    # Run the implemented business logic here
                    url, status, message, results = process_run_task(
                        type="post_plan", data=plan_json, run_id=run_id, structured_logger=structured_logger
                    )

                    # Write output to cloudwatch log
                    cw_log_group_dest = os.environ.get("CW_LOG_GROUP_NAME", None)
                    if cw_log_group_dest != None:
                        write_run_task_log(run_id, results, cw_log_group_dest)

                if error:
                    logger.debug(f"{error}")
                    message = error
                    structured_logger.log_error(
                        error_type="PlanFetchError",
                        error_message=error
                    )

            runtask_response = {
                "url": url,
                "status": status,
                "message": message,
                "results": results,
            }
            return runtask_response

        else:
            return runtask_response

    except Exception as e:
        logger.error(f"Error: {e}")
        structured_logger.log_error(
            error_type=type(e).__name__,
            error_message=str(e)
        )
        runtask_response["message"] = (
            "HCP Terraform run task failed, please look into the service logs for more details."
        )
        return runtask_response
