import json
import os
import boto3
import botocore

from bedrock_utils import logger, stream_messages
from utils.error_handling import retry_with_backoff

model_id = os.environ.get("BEDROCK_LLM_MODEL")
guardrail_id = os.environ.get("BEDROCK_GUARDRAIL_ID", None)
guardrail_version = os.environ.get("BEDROCK_GUARDRAIL_VERSION", None)

config = botocore.config.Config(
    read_timeout=300, connect_timeout=300, retries={"max_attempts": 0}
)

session = boto3.Session()
bedrock_client = session.client(
    service_name="bedrock-runtime", config=config
)

def eval(tf_plan_json, tool_registry=None, structured_logger=None, metrics_emitter=None, output_formatter=None):
    logger.info("##### Running AI analysis with structured output #####")
    
    resource_changes = tf_plan_json.get("resource_changes", [])
    add_count = sum(1 for r in resource_changes if r.get("change", {}).get("actions") == ["create"])
    change_count = sum(1 for r in resource_changes if r.get("change", {}).get("actions") == ["update"])
    delete_count = sum(1 for r in resource_changes if r.get("change", {}).get("actions") == ["delete"])
    
    logger.info(f"Resource changes: {add_count} to add, {change_count} to change, {delete_count} to destroy")
    
    # Single comprehensive prompt for all three sections
    prompt = f"""
Analyze this Terraform plan and provide THREE distinct sections:

**SECTION 1: Plan-Summary**
Format as markdown with these subsections:
- **Networking**: VPCs, subnets, route tables with CIDR blocks
- **Security & Defaults**: Security groups (ports, protocols, CIDR), IAM roles, encryption
- **Compute**: EC2 instances (type, AMI ID, availability zone)
- **Storage**: EBS volumes, S3 buckets (encryption, public access)
- **Tags**: Common tags applied

**SECTION 2: Impact-Analysis**
Format as markdown with these subsections:
- **🚨 Security Concerns**: Critical/High/Medium security issues (public access, open ports, unencrypted storage)
- **⚠️ Configuration Issues**: Missing tags, deprecated resources, configuration problems
- **📊 Operational Impact**: Infrastructure changes, availability impact, cost implications
- **💡 Recommendations**: Priority fixes and best practices

**SECTION 3: AMI-Summary**
Format as markdown with these subsections:
- **Current AMIs**: List any existing AMI IDs being replaced
- **New/Updated AMIs**: List new AMI IDs being deployed with descriptions
- **Validation**: Instance type validation, security assessment
- **Recommendations**: AMI update recommendations, security improvements

Resource Summary: {add_count} to add, {change_count} to change, {delete_count} to destroy

Terraform Plan: {json.dumps(resource_changes[:20])}
"""

    messages = [{"role": "user", "content": [{"text": prompt}]}]

    stop_reason, response = retry_with_backoff(
        lambda: stream_messages(
            bedrock_client=bedrock_client,
            model_id=model_id,
            messages=messages,
            system_text="You are an AWS infrastructure analyst. Provide detailed analysis in three distinct sections: Plan-Summary, Impact-Analysis, and AMI-Summary. Be specific with resource details.",
            tool_config=None,
        )
    )

    if response and "content" in response and len(response["content"]) > 0:
        full_result = response["content"][0]["text"]
    else:
        full_result = f"Analysis: {add_count} resources to add, {change_count} to change, {delete_count} to destroy"

    logger.info("##### Analysis Complete #####")
    
    # Split the result into three sections
    plan_summary = extract_section(full_result, "Plan-Summary", "SECTION 1")
    impact_analysis = extract_section(full_result, "Impact-Analysis", "SECTION 2")
    ami_summary = extract_section(full_result, "AMI-Summary", "SECTION 3")

    # Create three separate result outcomes
    results = [
        {
            "type": "task-result-outcomes",
            "attributes": {
                "outcome-id": "plan-summary",
                "description": "📋 Plan-Summary",
                "body": plan_summary[:9000] if plan_summary else "No plan summary available",
                "tags": {
                    "status": [{"label": "Analyzed", "level": "info"}]
                }
            }
        },
        {
            "type": "task-result-outcomes",
            "attributes": {
                "outcome-id": "impact-analysis",
                "description": "🔍 Impact-Analysis",
                "body": impact_analysis[:9000] if impact_analysis else "No impact analysis available",
                "tags": {
                    "status": [{"label": "Analyzed", "level": "info"}]
                }
            }
        },
        {
            "type": "task-result-outcomes",
            "attributes": {
                "outcome-id": "ami-summary",
                "description": "🖥️ AMI-Summary",
                "body": ami_summary[:9000] if ami_summary else "No AMI summary available",
                "tags": {
                    "status": [{"label": "Analyzed", "level": "info"}]
                }
            }
        }
    ]

    return "🤖 AI-Powered Terraform Plan Analysis", results


def extract_section(text, section_name, section_marker):
    """
    Extract a specific section from the AI response.
    
    Args:
        text: Full AI response text
        section_name: Name of section to extract (e.g., "Plan-Summary")
        section_marker: Alternative marker (e.g., "SECTION 1")
    
    Returns:
        str: Extracted section text
    """
    # Try to find section by name or marker
    markers = [
        f"**SECTION 1: {section_name}**",
        f"**{section_name}**",
        f"## {section_name}",
        f"# {section_name}",
        section_marker,
        f"**{section_marker}:",
    ]
    
    start_idx = -1
    for marker in markers:
        idx = text.find(marker)
        if idx != -1:
            start_idx = idx
            break
    
    if start_idx == -1:
        # Section not found, return portion of text based on section type
        if "Plan" in section_name:
            return text[:len(text)//3]
        elif "Impact" in section_name:
            return text[len(text)//3:2*len(text)//3]
        else:  # AMI
            return text[2*len(text)//3:]
    
    # Find the end of this section (start of next section or end of text)
    next_section_markers = [
        "**SECTION 2:",
        "**SECTION 3:",
        "**Impact-Analysis**",
        "**AMI-Summary**",
        "## Impact-Analysis",
        "## AMI-Summary",
    ]
    
    end_idx = len(text)
    for marker in next_section_markers:
        idx = text.find(marker, start_idx + 1)
        if idx != -1 and idx < end_idx:
            end_idx = idx
            break
    
    return text[start_idx:end_idx].strip()

