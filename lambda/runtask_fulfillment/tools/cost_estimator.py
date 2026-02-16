"""
Cost Estimator Tool for estimating infrastructure costs.

This tool estimates monthly EC2 costs using AWS Pricing API and provides:
- Monthly cost estimates for EC2 instances
- Cost comparison between old and new configurations
- High-impact flagging for cost increases exceeding 20%

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError
import json

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.base import BaseTool
from models.tool_models import ToolInput, ToolOutput, Finding, Severity
from pydantic import Field
from bedrock_utils import logger


class CostEstimatorInput(ToolInput):
    """Input model for cost estimator"""
    instance_type: str = Field(..., description="EC2 instance type to estimate costs for (e.g., t3.micro)")
    region: str = Field(..., description="AWS region for pricing (e.g., us-east-1)")
    hours_per_month: int = Field(730, description="Hours per month for cost calculation (default: 730)")
    old_instance_type: Optional[str] = Field(None, description="Previous instance type for cost comparison")


class CostEstimatorTool(BaseTool):
    """
    Estimates infrastructure costs including:
    - Monthly EC2 instance costs using AWS Pricing API
    - Cost comparison between old and new configurations
    - High-impact flagging for increases exceeding 20%
    - Graceful fallback with cached/estimated values on API failures
    """
    
    # Fallback pricing estimates (USD per hour) for common instance types
    # Used when Pricing API is unavailable
    FALLBACK_PRICING = {
        # T3 family
        "t3.nano": 0.0052,
        "t3.micro": 0.0104,
        "t3.small": 0.0208,
        "t3.medium": 0.0416,
        "t3.large": 0.0832,
        "t3.xlarge": 0.1664,
        "t3.2xlarge": 0.3328,
        # T3a family
        "t3a.nano": 0.0047,
        "t3a.micro": 0.0094,
        "t3a.small": 0.0188,
        "t3a.medium": 0.0376,
        "t3a.large": 0.0752,
        "t3a.xlarge": 0.1504,
        "t3a.2xlarge": 0.3008,
        # M5 family
        "m5.large": 0.096,
        "m5.xlarge": 0.192,
        "m5.2xlarge": 0.384,
        "m5.4xlarge": 0.768,
        # C5 family
        "c5.large": 0.085,
        "c5.xlarge": 0.17,
        "c5.2xlarge": 0.34,
        "c5.4xlarge": 0.68,
    }
    
    # Cost increase threshold for high-impact flagging
    COST_THRESHOLD_PERCENT = 20
    
    def __init__(self):
        """Initialize cost estimator with AWS Pricing client"""
        self.session = boto3.Session()
        self._pricing_client = None
    
    @property
    def pricing_client(self):
        """Lazy load Pricing client (must use us-east-1 region)"""
        if self._pricing_client is None:
            # AWS Pricing API is only available in us-east-1
            self._pricing_client = self.session.client('pricing', region_name='us-east-1')
        return self._pricing_client
    
    @property
    def name(self) -> str:
        """Tool name for Bedrock function calling"""
        return "CostEstimator"
    
    @property
    def description(self) -> str:
        """Tool description for Bedrock AI model"""
        return (
            "Estimates monthly EC2 instance costs using AWS Pricing API. Calculates cost "
            "comparison between old and new instance types and flags cost increases exceeding "
            "20% as high-impact. Use this tool when analyzing EC2 instances in Terraform plans "
            "to provide cost impact analysis."
        )
    
    @property
    def input_schema(self) -> Dict[str, Any]:
        """JSON schema for tool inputs"""
        return {
            "type": "object",
            "properties": {
                "instance_type": {
                    "type": "string",
                    "description": "EC2 instance type to estimate costs for (e.g., t3.micro, m5.large)"
                },
                "region": {
                    "type": "string",
                    "description": "AWS region for pricing (e.g., us-east-1, eu-west-1)"
                },
                "hours_per_month": {
                    "type": "integer",
                    "description": "Hours per month for cost calculation (default: 730)",
                    "default": 730
                },
                "old_instance_type": {
                    "type": "string",
                    "description": "Previous instance type for cost comparison (optional)"
                }
            },
            "required": ["instance_type", "region"]
        }
    
    def execute(self, input_data: ToolInput) -> ToolOutput:
        """
        Execute cost estimation.
        
        Args:
            input_data: CostEstimatorInput with instance_type, region, hours_per_month, and optional old_instance_type
            
        Returns:
            ToolOutput with cost findings and comparison
        """
        try:
            # Validate input type
            if not isinstance(input_data, dict):
                validated_input = CostEstimatorInput(**input_data.model_dump())
            else:
                validated_input = CostEstimatorInput(**input_data)
            
            findings = []
            
            # Get cost for new instance type
            new_cost = self._get_instance_cost(
                validated_input.instance_type,
                validated_input.region,
                validated_input.hours_per_month
            )
            
            # If old instance type provided, calculate comparison
            if validated_input.old_instance_type:
                old_cost = self._get_instance_cost(
                    validated_input.old_instance_type,
                    validated_input.region,
                    validated_input.hours_per_month
                )
                
                cost_findings = self._compare_costs(
                    validated_input.old_instance_type,
                    old_cost,
                    validated_input.instance_type,
                    new_cost,
                    validated_input.hours_per_month
                )
                findings.extend(cost_findings)
            else:
                # No comparison, just report new cost
                findings.append(Finding(
                    severity=Severity.LOW,
                    title=f"Estimated monthly cost for {validated_input.instance_type}",
                    description=(
                        f"The EC2 instance type '{validated_input.instance_type}' in region "
                        f"'{validated_input.region}' will cost approximately ${new_cost:.2f} per month "
                        f"(based on {validated_input.hours_per_month} hours)."
                    ),
                    resource_address="aws_instance",
                    remediation=(
                        "Review the instance type selection to ensure it matches your workload requirements. "
                        "Consider using smaller instance types for development/testing environments."
                    )
                ))
            
            return ToolOutput(
                success=True,
                findings=findings
            )
            
        except Exception as e:
            logger.error(f"Cost estimation failed: {str(e)}")
            return ToolOutput(
                success=False,
                findings=[],
                error=f"Cost estimation error: {str(e)}"
            )
    
    def _get_instance_cost(self, instance_type: str, region: str, hours_per_month: int) -> float:
        """
        Get hourly cost for instance type and calculate monthly cost.
        
        Args:
            instance_type: EC2 instance type
            region: AWS region
            hours_per_month: Hours per month for calculation
            
        Returns:
            Monthly cost in USD
        """
        try:
            # Try to get pricing from AWS Pricing API
            hourly_rate = self._get_pricing_from_api(instance_type, region)
            
            if hourly_rate is not None:
                monthly_cost = hourly_rate * hours_per_month
                logger.info(f"Got pricing from API for {instance_type}: ${hourly_rate:.4f}/hour")
                return monthly_cost
            
        except Exception as e:
            logger.warning(f"Failed to get pricing from API for {instance_type}: {str(e)}")
        
        # Fallback to cached estimates
        return self._get_fallback_cost(instance_type, hours_per_month)
    
    def _get_pricing_from_api(self, instance_type: str, region: str) -> Optional[float]:
        """
        Get pricing from AWS Pricing API.
        
        Args:
            instance_type: EC2 instance type
            region: AWS region
            
        Returns:
            Hourly rate in USD, or None if not found
        """
        try:
            # Map region code to region name for Pricing API
            region_name = self._get_region_name(region)
            
            # Query Pricing API
            response = self.pricing_client.get_products(
                ServiceCode='AmazonEC2',
                Filters=[
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'instanceType',
                        'Value': instance_type
                    },
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'location',
                        'Value': region_name
                    },
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'operatingSystem',
                        'Value': 'Linux'
                    },
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'tenancy',
                        'Value': 'Shared'
                    },
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'preInstalledSw',
                        'Value': 'NA'
                    },
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'capacitystatus',
                        'Value': 'Used'
                    }
                ],
                MaxResults=1
            )
            
            if not response.get('PriceList'):
                logger.warning(f"No pricing found for {instance_type} in {region}")
                return None
            
            # Parse pricing data
            price_item = json.loads(response['PriceList'][0])
            on_demand = price_item.get('terms', {}).get('OnDemand', {})
            
            if not on_demand:
                return None
            
            # Get the first (and only) price dimension
            for offer_term in on_demand.values():
                for price_dimension in offer_term.get('priceDimensions', {}).values():
                    price_per_unit = price_dimension.get('pricePerUnit', {}).get('USD')
                    if price_per_unit:
                        return float(price_per_unit)
            
            return None
            
        except ClientError as e:
            logger.error(f"Pricing API error: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error parsing pricing data: {str(e)}")
            return None
    
    def _get_region_name(self, region_code: str) -> str:
        """
        Map region code to region name for Pricing API.
        
        Args:
            region_code: AWS region code (e.g., us-east-1)
            
        Returns:
            Region name for Pricing API (e.g., US East (N. Virginia))
        """
        region_map = {
            'us-east-1': 'US East (N. Virginia)',
            'us-east-2': 'US East (Ohio)',
            'us-west-1': 'US West (N. California)',
            'us-west-2': 'US West (Oregon)',
            'eu-west-1': 'EU (Ireland)',
            'eu-west-2': 'EU (London)',
            'eu-west-3': 'EU (Paris)',
            'eu-central-1': 'EU (Frankfurt)',
            'eu-north-1': 'EU (Stockholm)',
            'ap-northeast-1': 'Asia Pacific (Tokyo)',
            'ap-northeast-2': 'Asia Pacific (Seoul)',
            'ap-southeast-1': 'Asia Pacific (Singapore)',
            'ap-southeast-2': 'Asia Pacific (Sydney)',
            'ap-south-1': 'Asia Pacific (Mumbai)',
            'ca-central-1': 'Canada (Central)',
            'sa-east-1': 'South America (Sao Paulo)',
        }
        
        return region_map.get(region_code, 'US East (N. Virginia)')
    
    def _get_fallback_cost(self, instance_type: str, hours_per_month: int) -> float:
        """
        Get fallback cost estimate from cached pricing.
        
        Args:
            instance_type: EC2 instance type
            hours_per_month: Hours per month for calculation
            
        Returns:
            Monthly cost in USD
        """
        hourly_rate = self.FALLBACK_PRICING.get(instance_type)
        
        if hourly_rate is None:
            # No cached pricing, estimate based on instance family
            hourly_rate = self._estimate_cost_by_family(instance_type)
        
        monthly_cost = hourly_rate * hours_per_month
        logger.info(f"Using fallback pricing for {instance_type}: ${hourly_rate:.4f}/hour (estimated)")
        return monthly_cost
    
    def _estimate_cost_by_family(self, instance_type: str) -> float:
        """
        Estimate cost based on instance family when exact pricing unavailable.
        
        Args:
            instance_type: EC2 instance type
            
        Returns:
            Estimated hourly rate in USD
        """
        # Parse instance family and size
        parts = instance_type.split('.')
        if len(parts) != 2:
            # Unknown format, use conservative estimate
            return 0.10
        
        family, size = parts
        
        # Size multipliers (relative to base size)
        size_multipliers = {
            'nano': 0.5,
            'micro': 1.0,
            'small': 2.0,
            'medium': 4.0,
            'large': 8.0,
            'xlarge': 16.0,
            '2xlarge': 32.0,
            '4xlarge': 64.0,
            '8xlarge': 128.0,
        }
        
        # Base rates for common families (micro size)
        family_base_rates = {
            't3': 0.0104,
            't3a': 0.0094,
            't2': 0.0116,
            'm5': 0.024,
            'm6i': 0.024,
            'c5': 0.0212,
            'c6i': 0.0212,
            'r5': 0.0315,
            'r6i': 0.0315,
        }
        
        # Get base rate for family (default to t3 if unknown)
        base_rate = family_base_rates.get(family, 0.0104)
        
        # Get size multiplier (default to 1.0 if unknown)
        multiplier = size_multipliers.get(size, 1.0)
        
        # Calculate estimated rate
        estimated_rate = base_rate * multiplier
        
        logger.info(f"Estimated rate for {instance_type}: ${estimated_rate:.4f}/hour (family-based estimate)")
        return estimated_rate
    
    def _compare_costs(
        self,
        old_instance_type: str,
        old_cost: float,
        new_instance_type: str,
        new_cost: float,
        hours_per_month: int
    ) -> list[Finding]:
        """
        Compare costs between old and new instance types.
        
        Args:
            old_instance_type: Previous instance type
            old_cost: Monthly cost of old instance
            new_instance_type: New instance type
            new_cost: Monthly cost of new instance
            hours_per_month: Hours per month for calculation
            
        Returns:
            List of findings with cost comparison
        """
        findings = []
        
        # Calculate cost difference
        cost_diff = new_cost - old_cost
        
        # Calculate percentage change
        if old_cost > 0:
            percent_change = (cost_diff / old_cost) * 100
        else:
            # Old cost was zero (new resource)
            percent_change = 100 if new_cost > 0 else 0
        
        # Determine severity based on threshold
        if percent_change > self.COST_THRESHOLD_PERCENT:
            severity = Severity.HIGH
            title = f"High-impact cost increase: {old_instance_type} → {new_instance_type}"
            description = (
                f"Changing from '{old_instance_type}' to '{new_instance_type}' will increase "
                f"monthly costs by ${abs(cost_diff):.2f} ({percent_change:.1f}% increase). "
                f"Old cost: ${old_cost:.2f}/month, New cost: ${new_cost:.2f}/month. "
                f"This exceeds the {self.COST_THRESHOLD_PERCENT}% cost increase threshold."
            )
            remediation = (
                f"Review the need for upgrading to '{new_instance_type}'. Consider:\n"
                f"- Is the increased capacity required for your workload?\n"
                f"- Can you use a smaller instance type with similar performance?\n"
                f"- Are there cost optimization opportunities (Reserved Instances, Savings Plans)?\n"
                f"- Is this change for a production or development environment?"
            )
        elif percent_change > 0:
            severity = Severity.LOW
            title = f"Cost increase: {old_instance_type} → {new_instance_type}"
            description = (
                f"Changing from '{old_instance_type}' to '{new_instance_type}' will increase "
                f"monthly costs by ${abs(cost_diff):.2f} ({percent_change:.1f}% increase). "
                f"Old cost: ${old_cost:.2f}/month, New cost: ${new_cost:.2f}/month."
            )
            remediation = (
                f"The cost increase is within acceptable limits (<{self.COST_THRESHOLD_PERCENT}%). "
                f"Ensure the instance type change aligns with your workload requirements."
            )
        elif percent_change < 0:
            severity = Severity.LOW
            title = f"Cost savings: {old_instance_type} → {new_instance_type}"
            description = (
                f"Changing from '{old_instance_type}' to '{new_instance_type}' will decrease "
                f"monthly costs by ${abs(cost_diff):.2f} ({abs(percent_change):.1f}% decrease). "
                f"Old cost: ${old_cost:.2f}/month, New cost: ${new_cost:.2f}/month."
            )
            remediation = (
                "This change will result in cost savings. Ensure the smaller instance type "
                "can handle your workload requirements without performance degradation."
            )
        else:
            # No cost change
            severity = Severity.LOW
            title = f"No cost change: {old_instance_type} → {new_instance_type}"
            description = (
                f"Changing from '{old_instance_type}' to '{new_instance_type}' will have "
                f"minimal cost impact. Both instance types cost approximately ${new_cost:.2f}/month."
            )
            remediation = "No cost-related action required."
        
        findings.append(Finding(
            severity=severity,
            title=title,
            description=description,
            resource_address="aws_instance",
            remediation=remediation
        ))
        
        return findings
