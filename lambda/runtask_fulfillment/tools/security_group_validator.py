"""
Security Group Validator Tool for validating security group configurations.

This tool validates security group rules including:
- Identifying overly permissive ingress rules (0.0.0.0/0 on sensitive ports)
- Assigning severity levels based on port sensitivity

The tool parses security group rules from Terraform plan JSON without making AWS API calls.

Requirements: 2.3, 4.4
"""

import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.base import BaseTool
from models.tool_models import ToolInput, ToolOutput, Finding, Severity
from pydantic import Field
from bedrock_utils import logger


class SecurityGroupValidatorInput(ToolInput):
    """Input model for Security Group validator"""
    security_group_name: str = Field(..., description="Security group name or ID being validated")
    ingress_rules: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of ingress rules with keys: from_port, to_port, protocol, cidr_blocks"
    )
    egress_rules: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of egress rules with keys: from_port, to_port, protocol, cidr_blocks"
    )


class SecurityGroupValidatorTool(BaseTool):
    """
    Validates security group configurations including:
    - Overly permissive ingress rules (0.0.0.0/0 on sensitive ports)
    - Severity assignment based on port sensitivity
    
    Sensitive ports:
    - SSH (22), RDP (3389): CRITICAL severity
    - MySQL (3306), PostgreSQL (5432): HIGH severity
    
    This tool parses configuration from Terraform plan JSON and does not make AWS API calls.
    """
    
    # Define sensitive ports and their severity levels
    SENSITIVE_PORTS = {
        22: ("SSH", Severity.CRITICAL),
        3389: ("RDP", Severity.CRITICAL),
        3306: ("MySQL", Severity.HIGH),
        5432: ("PostgreSQL", Severity.HIGH),
    }
    
    @property
    def name(self) -> str:
        """Tool name for Bedrock function calling"""
        return "SecurityGroupValidator"
    
    @property
    def description(self) -> str:
        """Tool description for Bedrock AI model"""
        return (
            "Validates security group configurations to identify overly permissive rules. "
            "Checks for 0.0.0.0/0 CIDR blocks on sensitive ports including SSH (22), "
            "RDP (3389), MySQL (3306), and PostgreSQL (5432). Use this tool when analyzing "
            "security groups in Terraform plans to identify security risks."
        )
    
    @property
    def input_schema(self) -> Dict[str, Any]:
        """JSON schema for tool inputs"""
        return {
            "type": "object",
            "properties": {
                "security_group_name": {
                    "type": "string",
                    "description": "Security group name or ID being validated"
                },
                "ingress_rules": {
                    "type": "array",
                    "description": "List of ingress rules",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from_port": {
                                "type": "integer",
                                "description": "Starting port number"
                            },
                            "to_port": {
                                "type": "integer",
                                "description": "Ending port number"
                            },
                            "protocol": {
                                "type": "string",
                                "description": "Protocol (tcp, udp, icmp, or -1 for all)"
                            },
                            "cidr_blocks": {
                                "type": "array",
                                "description": "List of CIDR blocks",
                                "items": {"type": "string"}
                            }
                        }
                    }
                },
                "egress_rules": {
                    "type": "array",
                    "description": "List of egress rules",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from_port": {
                                "type": "integer",
                                "description": "Starting port number"
                            },
                            "to_port": {
                                "type": "integer",
                                "description": "Ending port number"
                            },
                            "protocol": {
                                "type": "string",
                                "description": "Protocol (tcp, udp, icmp, or -1 for all)"
                            },
                            "cidr_blocks": {
                                "type": "array",
                                "description": "List of CIDR blocks",
                                "items": {"type": "string"}
                            }
                        }
                    }
                }
            },
            "required": ["security_group_name"]
        }
    
    def execute(self, input_data: ToolInput) -> ToolOutput:
        """
        Execute security group validation.
        
        Args:
            input_data: SecurityGroupValidatorInput with security_group_name, ingress_rules, and egress_rules
            
        Returns:
            ToolOutput with validation findings and remediation steps
        """
        try:
            # Validate input type
            if not isinstance(input_data, dict):
                validated_input = SecurityGroupValidatorInput(**input_data.model_dump())
            else:
                validated_input = SecurityGroupValidatorInput(**input_data)
            
            findings = []
            
            # Check ingress rules for overly permissive configurations
            ingress_findings = self._validate_ingress_rules(
                validated_input.security_group_name,
                validated_input.ingress_rules
            )
            findings.extend(ingress_findings)
            
            return ToolOutput(
                success=True,
                findings=findings
            )
            
        except Exception as e:
            logger.error(f"Security group validation failed: {str(e)}")
            return ToolOutput(
                success=False,
                findings=[],
                error=f"Security group validation error: {str(e)}"
            )
    
    def _validate_ingress_rules(
        self,
        sg_name: str,
        ingress_rules: List[Dict[str, Any]]
    ) -> list[Finding]:
        """
        Validate ingress rules for overly permissive configurations.
        
        Args:
            sg_name: Security group name
            ingress_rules: List of ingress rules
            
        Returns:
            List of findings for ingress rule validation
        """
        findings = []
        
        if not ingress_rules:
            logger.info(f"Security group '{sg_name}' has no ingress rules")
            return findings
        
        for rule in ingress_rules:
            # Extract rule details
            from_port = rule.get("from_port")
            to_port = rule.get("to_port")
            protocol = rule.get("protocol", "")
            cidr_blocks = rule.get("cidr_blocks", [])
            
            # Check if rule allows access from anywhere (0.0.0.0/0)
            if "0.0.0.0/0" not in cidr_blocks:
                continue
            
            # Check if this rule exposes sensitive ports
            rule_findings = self._check_sensitive_ports(
                sg_name,
                from_port,
                to_port,
                protocol,
                cidr_blocks
            )
            findings.extend(rule_findings)
        
        return findings
    
    def _check_sensitive_ports(
        self,
        sg_name: str,
        from_port: Optional[int],
        to_port: Optional[int],
        protocol: str,
        cidr_blocks: List[str]
    ) -> list[Finding]:
        """
        Check if rule exposes sensitive ports to 0.0.0.0/0.
        
        Args:
            sg_name: Security group name
            from_port: Starting port number
            to_port: Ending port number
            protocol: Protocol (tcp, udp, icmp, or -1 for all)
            cidr_blocks: List of CIDR blocks
            
        Returns:
            List of findings for sensitive port exposure
        """
        findings = []
        
        # Handle special cases
        if protocol == "-1" or from_port is None or to_port is None:
            # Rule allows all protocols/ports
            findings.append(Finding(
                severity=Severity.CRITICAL,
                title=f"Security group '{sg_name}' allows all traffic from anywhere",
                description=(
                    f"The security group '{sg_name}' has a rule that allows ALL traffic "
                    f"(all protocols and ports) from 0.0.0.0/0. This is extremely dangerous "
                    f"and exposes all services to the internet."
                ),
                resource_address=f"aws_security_group.{sg_name}",
                remediation=(
                    "Remove the overly permissive rule and create specific rules for only "
                    "the required ports and protocols. Restrict source CIDR blocks to known "
                    "IP ranges or security groups."
                )
            ))
            return findings
        
        # Check each sensitive port
        for port, (service_name, severity) in self.SENSITIVE_PORTS.items():
            if from_port <= port <= to_port:
                # Sensitive port is exposed
                findings.append(Finding(
                    severity=severity,
                    title=f"Security group '{sg_name}' exposes {service_name} (port {port}) to the internet",
                    description=(
                        f"The security group '{sg_name}' allows {service_name} access on port {port} "
                        f"from 0.0.0.0/0 (anywhere on the internet). This exposes the service to "
                        f"potential brute force attacks, unauthorized access, and security breaches."
                    ),
                    resource_address=f"aws_security_group.{sg_name}",
                    remediation=self._get_remediation_for_port(port, service_name)
                ))
        
        # If no sensitive ports found but rule is still overly permissive, log it
        if not findings and from_port is not None and to_port is not None:
            logger.info(
                f"Security group '{sg_name}' allows ports {from_port}-{to_port} "
                f"from 0.0.0.0/0 (not a sensitive port)"
            )
        
        return findings
    
    def _get_remediation_for_port(self, port: int, service_name: str) -> str:
        """
        Get specific remediation guidance for a sensitive port.
        
        Args:
            port: Port number
            service_name: Service name (SSH, RDP, MySQL, PostgreSQL)
            
        Returns:
            Remediation guidance string
        """
        remediations = {
            22: (
                "Restrict SSH access to specific IP ranges or use AWS Systems Manager Session Manager "
                "for secure access without exposing SSH to the internet. If SSH access is required, "
                "limit the source CIDR to your organization's IP ranges or VPN endpoints."
            ),
            3389: (
                "Restrict RDP access to specific IP ranges or use AWS Systems Manager Session Manager "
                "for secure access without exposing RDP to the internet. If RDP access is required, "
                "limit the source CIDR to your organization's IP ranges or VPN endpoints."
            ),
            3306: (
                "MySQL databases should never be exposed to the internet. Restrict access to "
                "application security groups or specific VPC CIDR blocks. Use VPC peering or "
                "AWS PrivateLink for cross-VPC database access."
            ),
            5432: (
                "PostgreSQL databases should never be exposed to the internet. Restrict access to "
                "application security groups or specific VPC CIDR blocks. Use VPC peering or "
                "AWS PrivateLink for cross-VPC database access."
            )
        }
        
        return remediations.get(
            port,
            f"Restrict {service_name} access to specific IP ranges or security groups. "
            f"Remove 0.0.0.0/0 from the source CIDR blocks."
        )
