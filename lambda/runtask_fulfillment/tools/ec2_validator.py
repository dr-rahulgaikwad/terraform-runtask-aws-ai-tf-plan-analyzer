"""
EC2 Validator Tool for validating EC2 instance configurations.

This tool validates EC2 instance type availability and integrates AMI release notes
functionality to provide comprehensive EC2 validation.

Requirements: 2.1, 2.5
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.base import BaseTool
from models.tool_models import ToolInput, ToolOutput, Finding, Severity
from pydantic import Field
from bedrock_utils import logger


class EC2ValidatorInput(ToolInput):
    """Input model for EC2 validator"""
    instance_type: str = Field(..., description="EC2 instance type to validate (e.g., t3.micro)")
    region: str = Field(..., description="AWS region to check availability")
    ami_id: Optional[str] = Field(None, description="AMI ID to validate (optional)")


class EC2ValidatorTool(BaseTool):
    """
    Validates EC2 instance configurations including:
    - Instance type availability in specified region
    - AMI release notes for ECS-optimized AMIs
    - Instance type recommendations
    """
    
    def __init__(self):
        """Initialize EC2 validator with AWS clients"""
        self.session = boto3.Session()
        # Lazy import to avoid module-level boto3 client creation
        self._ami_validator = None
    
    @property
    def ami_validator(self):
        """Lazy load AMI validator to avoid import-time AWS client creation"""
        if self._ami_validator is None:
            from tools.get_ami_releases import GetECSAmisReleases
            self._ami_validator = GetECSAmisReleases()
        return self._ami_validator
    
    @property
    def name(self) -> str:
        """Tool name for Bedrock function calling"""
        return "EC2Validator"
    
    @property
    def description(self) -> str:
        """Tool description for Bedrock AI model"""
        return (
            "Validates EC2 instance configurations including instance type availability "
            "in the specified region and AMI release information. Use this tool when "
            "analyzing EC2 instances in Terraform plans to check for availability issues "
            "and get AMI release notes."
        )
    
    @property
    def input_schema(self) -> Dict[str, Any]:
        """JSON schema for tool inputs"""
        return {
            "type": "object",
            "properties": {
                "instance_type": {
                    "type": "string",
                    "description": "EC2 instance type to validate (e.g., t3.micro, m5.large)"
                },
                "region": {
                    "type": "string",
                    "description": "AWS region to check availability (e.g., us-east-1)"
                },
                "ami_id": {
                    "type": "string",
                    "description": "Optional AMI ID to validate and get release notes"
                }
            },
            "required": ["instance_type", "region"]
        }
    
    def execute(self, input_data: ToolInput) -> ToolOutput:
        """
        Execute EC2 validation.
        
        Args:
            input_data: EC2ValidatorInput with instance_type, region, and optional ami_id
            
        Returns:
            ToolOutput with validation findings and recommendations
        """
        try:
            # Validate input type
            if not isinstance(input_data, dict):
                validated_input = EC2ValidatorInput(**input_data.model_dump())
            else:
                validated_input = EC2ValidatorInput(**input_data)
            
            findings = []
            
            # Check instance type availability
            instance_findings = self._validate_instance_type(
                validated_input.instance_type,
                validated_input.region
            )
            findings.extend(instance_findings)
            
            # Check AMI release notes if AMI ID provided
            if validated_input.ami_id:
                ami_findings = self._validate_ami(
                    validated_input.ami_id,
                    validated_input.instance_type
                )
                findings.extend(ami_findings)
            
            return ToolOutput(
                success=True,
                findings=findings
            )
            
        except Exception as e:
            logger.error(f"EC2 validation failed: {str(e)}")
            return ToolOutput(
                success=False,
                findings=[],
                error=f"EC2 validation error: {str(e)}"
            )
    
    def _validate_instance_type(self, instance_type: str, region: str) -> list[Finding]:
        """
        Validate instance type availability in region.
        
        Args:
            instance_type: EC2 instance type (e.g., t3.micro)
            region: AWS region (e.g., us-east-1)
            
        Returns:
            List of findings for instance type validation
        """
        findings = []
        
        try:
            # Create regional EC2 client
            ec2_client = self.session.client('ec2', region_name=region)
            
            # Check if instance type is available in region
            response = ec2_client.describe_instance_types(
                InstanceTypes=[instance_type]
            )
            
            if not response.get('InstanceTypes'):
                # Instance type not available
                findings.append(Finding(
                    severity=Severity.HIGH,
                    title=f"Instance type {instance_type} not available in {region}",
                    description=(
                        f"The instance type '{instance_type}' is not available in region '{region}'. "
                        f"This will cause deployment failures."
                    ),
                    resource_address="aws_instance",
                    remediation=self._get_instance_type_recommendation(instance_type, region)
                ))
            else:
                # Instance type is available - log success
                logger.info(f"Instance type {instance_type} is available in {region}")
                
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            
            if error_code == 'InvalidInstanceType':
                # Instance type doesn't exist at all
                findings.append(Finding(
                    severity=Severity.CRITICAL,
                    title=f"Invalid instance type: {instance_type}",
                    description=(
                        f"The instance type '{instance_type}' does not exist. "
                        f"This is likely a typo or an outdated instance type."
                    ),
                    resource_address="aws_instance",
                    remediation=(
                        f"Check the instance type name for typos. "
                        f"Consider using current generation instance types like t3, m5, or c5 families."
                    )
                ))
            else:
                # Other API errors
                logger.error(f"Error checking instance type: {str(e)}")
                findings.append(Finding(
                    severity=Severity.MEDIUM,
                    title=f"Unable to validate instance type {instance_type}",
                    description=f"API error while validating instance type: {str(e)}",
                    resource_address="aws_instance",
                    remediation="Verify AWS credentials and permissions for EC2 DescribeInstanceTypes API"
                ))
        
        return findings
    
    def _get_instance_type_recommendation(self, instance_type: str, region: str) -> str:
        """
        Get alternative instance type recommendations.
        
        Args:
            instance_type: Unavailable instance type
            region: Target region
            
        Returns:
            Recommendation string with alternative instance types
        """
        # Parse instance family (e.g., "t3" from "t3.micro")
        parts = instance_type.split('.')
        if len(parts) != 2:
            return f"Use a valid instance type format (e.g., t3.micro) in region {region}"
        
        family, size = parts
        
        # Suggest current generation alternatives
        recommendations = {
            't2': 't3',
            't3': 't3a',
            'm4': 'm5',
            'm5': 'm6i',
            'c4': 'c5',
            'c5': 'c6i',
            'r4': 'r5',
            'r5': 'r6i'
        }
        
        alternative_family = recommendations.get(family, 't3')
        alternative_type = f"{alternative_family}.{size}"
        
        return (
            f"Consider using '{alternative_type}' instead, which is a current generation "
            f"instance type available in most regions. Alternatively, check AWS documentation "
            f"for instance type availability in {region}."
        )
    
    def _validate_ami(self, ami_id: str, instance_type: str) -> list[Finding]:
        """
        Validate AMI and get release notes for ECS-optimized AMIs.
        
        Args:
            ami_id: AMI ID to validate
            instance_type: Instance type for compatibility check
            
        Returns:
            List of findings for AMI validation
        """
        findings = []
        
        try:
            # Get AMI release information using existing functionality
            releases_info = self.ami_validator.execute([ami_id])
            
            if releases_info:
                # AMI found in ECS releases - provide informational finding
                for release in releases_info:
                    logger.info(f"Found ECS AMI release info: {release.get('ami_name')}")
                    
                    findings.append(Finding(
                        severity=Severity.LOW,
                        title=f"ECS-optimized AMI detected: {release.get('ami_name')}",
                        description=(
                            f"Using ECS-optimized AMI '{release.get('ami_name')}' "
                            f"({ami_id}). OS: {release.get('os_name', 'N/A')}"
                        ),
                        resource_address="aws_instance",
                        remediation=(
                            "Ensure this AMI version is up to date. Check AWS ECS AMI release notes "
                            "for the latest security patches and features."
                        )
                    ))
            else:
                # Not an ECS AMI or not found in releases
                logger.info(f"AMI {ami_id} is not an ECS-optimized AMI or release info not available")
                
        except Exception as e:
            logger.error(f"Error validating AMI {ami_id}: {str(e)}")
            # Don't fail the entire validation for AMI issues
            findings.append(Finding(
                severity=Severity.LOW,
                title=f"Unable to retrieve AMI release information",
                description=f"Could not fetch release notes for AMI {ami_id}: {str(e)}",
                resource_address="aws_instance",
                remediation="Verify the AMI ID is correct and accessible in your AWS account"
            ))
        
        return findings
