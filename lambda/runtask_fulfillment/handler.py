import json
import logging
import os
import time
import signal

import boto3

import ai_simple as ai
import runtask_utils
from utils.error_handling import is_retryable_error

region = os.environ.get("AWS_REGION", None)
dev_mode = os.environ.get("DEV_MODE", "true")
log_level = os.environ.get("log_level", logging.INFO)

logger = logging.getLogger()
logger.setLevel(log_level)

session = boto3.Session()
cwl_client = session.client('logs')

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
def process_run_task(type: str, data: str, run_id: str):
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
            logger.info(f"Processing post_plan for run_id: {run_id}")
            
            # Execute AI analysis
            message, results = ai.eval(data)
    
    except TimeoutException as e:
        # Handle Lambda timeout gracefully - return partial results
        logger.warning(f"Lambda execution approaching timeout: {e}")
        
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
    
    # Log execution time
    duration_ms = (time.time() - start_time) * 1000
    logger.info(f"Run task completed in {duration_ms:.2f}ms with status: {status}")

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
    
    # Get run_id for logging
    run_id = event.get("payload", {}).get("detail", {}).get("run_id", "unknown")

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
            
            logger.info(f"Processing run task for org: {organization_name}, workspace: {workspace_id}, run: {run_id}")

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
                    type="pre_plan", data=config_file, run_id=run_id
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
                        type="post_plan", data=plan_json, run_id=run_id
                    )

                    # Write output to cloudwatch log
                    cw_log_group_dest = os.environ.get("CW_LOG_GROUP_NAME", None)
                    if cw_log_group_dest != None:
                        write_run_task_log(run_id, results, cw_log_group_dest)

                if error:
                    logger.error(f"Error fetching plan: {error}")
                    message = error

            runtask_response = {
                "url": url,
                "status": status,
                "message": message,
                "results": results,
            }
            
            # Send callback directly to HCP Terraform (bypass Step Function delay)
            logger.info("Sending callback directly to HCP Terraform")
            try:
                import json
                from urllib.request import urlopen, Request
                
                payload = {
                    "data": {
                        "attributes": runtask_response,
                        "type": "task-results",
                        "relationships": {
                            "outcomes": {
                                "data": results,
                            }
                        },
                    }
                }
                
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-type": "application/vnd.api+json",
                }
                
                request = Request(
                    task_result_callback_url,
                    headers=headers,
                    data=bytes(json.dumps(payload), encoding="utf-8"),
                    method="PATCH"
                )
                
                with urlopen(request, timeout=10) as response:
                    logger.info(f"Callback sent successfully: {response.status}")
                    
            except Exception as e:
                logger.error(f"Failed to send callback: {e}")
                # Still return response for Step Function as fallback
            
            return runtask_response

        else:
            return runtask_response

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        runtask_response["message"] = (
            "HCP Terraform run task failed, please look into the service logs for more details."
        )
        return runtask_response
