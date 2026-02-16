"""
S3 Validator Tool for validating S3 bucket configurations.

This tool validates S3 bucket security configurations including:
- Public access block settings
- Encryption configuration (AES256 or KMS)

The tool parses S3 bucket configuration from Terraform plan JSON without making AWS API calls.

Requirements: 2.2
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.base import BaseTool
from models.tool_models import ToolInput, ToolOutput, Finding, Severity
from pydantic import Field
from bedrock_utils import logger


class S3ValidatorInput(ToolInput):
    """Input model for S3 validator"""
    bucket_name: str = Field(..., description="S3 bucket name being validated")
    public_access_block: Optional[Dict[str, bool]] = Field(
        None,
        description="Public access block configuration with keys: block_public_acls, block_public_policy, ignore_public_acls, restrict_public_buckets"
    )
    encryption: Optional[Dict[str, Any]] = Field(
        None,
        description="Encryption configuration with keys: sse_algorithm (AES256 or aws:kms), kms_master_key_id"
    )


class S3ValidatorTool(BaseTool):
    """
    Validates S3 bucket configurations including:
    - Public access block settings
    - Encryption configuration (AES256 or KMS)
    
    This tool parses configuration from Terraform plan JSON and does not make AWS API calls.
    """
    
    @property
    def name(self) -> str:
        """Tool name for Bedrock function calling"""
        return "S3Validator"
    
    @property
    def description(self) -> str:
        """Tool description for Bedrock AI model"""
        return (
            "Validates S3 bucket security configurations including public access block settings "
            "and encryption configuration. Use this tool when analyzing S3 buckets in Terraform "
            "plans to identify security risks such as public access or missing encryption."
        )
    
    @property
    def input_schema(self) -> Dict[str, Any]:
        """JSON schema for tool inputs"""
        return {
            "type": "object",
            "properties": {
                "bucket_name": {
                    "type": "string",
                    "description": "S3 bucket name being validated"
                },
                "public_access_block": {
                    "type": "object",
                    "description": "Public access block configuration",
                    "properties": {
                        "block_public_acls": {"type": "boolean"},
                        "block_public_policy": {"type": "boolean"},
                        "ignore_public_acls": {"type": "boolean"},
                        "restrict_public_buckets": {"type": "boolean"}
                    }
                },
                "encryption": {
                    "type": "object",
                    "description": "Encryption configuration",
                    "properties": {
                        "sse_algorithm": {
                            "type": "string",
                            "description": "Server-side encryption algorithm (AES256 or aws:kms)"
                        },
                        "kms_master_key_id": {
                            "type": "string",
                            "description": "KMS key ID if using aws:kms encryption"
                        }
                    }
                }
            },
            "required": ["bucket_name"]
        }
    
    def execute(self, input_data: ToolInput) -> ToolOutput:
        """
        Execute S3 bucket validation.
        
        Args:
            input_data: S3ValidatorInput with bucket_name, public_access_block, and encryption config
            
        Returns:
            ToolOutput with validation findings and remediation steps
        """
        try:
            # Validate input type
            if not isinstance(input_data, dict):
                validated_input = S3ValidatorInput(**input_data.model_dump())
            else:
                validated_input = S3ValidatorInput(**input_data)
            
            findings = []
            
            # Check public access block settings
            public_access_findings = self._validate_public_access(
                validated_input.bucket_name,
                validated_input.public_access_block
            )
            findings.extend(public_access_findings)
            
            # Check encryption configuration
            encryption_findings = self._validate_encryption(
                validated_input.bucket_name,
                validated_input.encryption
            )
            findings.extend(encryption_findings)
            
            return ToolOutput(
                success=True,
                findings=findings
            )
            
        except Exception as e:
            logger.error(f"S3 validation failed: {str(e)}")
            return ToolOutput(
                success=False,
                findings=[],
                error=f"S3 validation error: {str(e)}"
            )
    
    def _validate_public_access(
        self,
        bucket_name: str,
        public_access_block: Optional[Dict[str, bool]]
    ) -> list[Finding]:
        """
        Validate public access block settings.
        
        Args:
            bucket_name: S3 bucket name
            public_access_block: Public access block configuration
            
        Returns:
            List of findings for public access validation
        """
        findings = []
        
        # If no public access block configuration provided, it means public access is not blocked
        if public_access_block is None:
            findings.append(Finding(
                severity=Severity.CRITICAL,
                title=f"S3 bucket '{bucket_name}' has no public access block configuration",
                description=(
                    f"The S3 bucket '{bucket_name}' does not have public access block settings configured. "
                    f"This means the bucket could potentially be made public through ACLs or bucket policies, "
                    f"exposing sensitive data to the internet."
                ),
                resource_address=f"aws_s3_bucket.{bucket_name}",
                remediation=(
                    "Add an aws_s3_bucket_public_access_block resource with all settings set to true:\n"
                    "resource \"aws_s3_bucket_public_access_block\" \"example\" {\n"
                    "  bucket = aws_s3_bucket.example.id\n"
                    "  block_public_acls       = true\n"
                    "  block_public_policy     = true\n"
                    "  ignore_public_acls      = true\n"
                    "  restrict_public_buckets = true\n"
                    "}"
                )
            ))
            return findings
        
        # Check each public access block setting
        required_settings = {
            "block_public_acls": "Block Public ACLs",
            "block_public_policy": "Block Public Policy",
            "ignore_public_acls": "Ignore Public ACLs",
            "restrict_public_buckets": "Restrict Public Buckets"
        }
        
        disabled_settings = []
        for setting_key, setting_name in required_settings.items():
            if not public_access_block.get(setting_key, False):
                disabled_settings.append(setting_name)
        
        if disabled_settings:
            findings.append(Finding(
                severity=Severity.CRITICAL,
                title=f"S3 bucket '{bucket_name}' has public access block settings disabled",
                description=(
                    f"The S3 bucket '{bucket_name}' has the following public access block settings disabled: "
                    f"{', '.join(disabled_settings)}. This could allow the bucket to be made public, "
                    f"potentially exposing sensitive data."
                ),
                resource_address=f"aws_s3_bucket.{bucket_name}",
                remediation=(
                    f"Enable all public access block settings for bucket '{bucket_name}':\n"
                    "resource \"aws_s3_bucket_public_access_block\" \"example\" {\n"
                    "  bucket = aws_s3_bucket.example.id\n"
                    "  block_public_acls       = true\n"
                    "  block_public_policy     = true\n"
                    "  ignore_public_acls      = true\n"
                    "  restrict_public_buckets = true\n"
                    "}"
                )
            ))
        else:
            logger.info(f"S3 bucket '{bucket_name}' has all public access block settings enabled")
        
        return findings
    
    def _validate_encryption(
        self,
        bucket_name: str,
        encryption: Optional[Dict[str, Any]]
    ) -> list[Finding]:
        """
        Validate encryption configuration.
        
        Args:
            bucket_name: S3 bucket name
            encryption: Encryption configuration
            
        Returns:
            List of findings for encryption validation
        """
        findings = []
        
        # If no encryption configuration provided, bucket is unencrypted
        if encryption is None:
            findings.append(Finding(
                severity=Severity.HIGH,
                title=f"S3 bucket '{bucket_name}' does not have encryption enabled",
                description=(
                    f"The S3 bucket '{bucket_name}' does not have server-side encryption configured. "
                    f"Data stored in this bucket will not be encrypted at rest, which violates "
                    f"security best practices and may not comply with regulatory requirements."
                ),
                resource_address=f"aws_s3_bucket.{bucket_name}",
                remediation=(
                    "Enable server-side encryption for the bucket using AES256 or KMS:\n"
                    "resource \"aws_s3_bucket_server_side_encryption_configuration\" \"example\" {\n"
                    "  bucket = aws_s3_bucket.example.id\n"
                    "  rule {\n"
                    "    apply_server_side_encryption_by_default {\n"
                    "      sse_algorithm = \"AES256\"  # or \"aws:kms\" for KMS encryption\n"
                    "    }\n"
                    "  }\n"
                    "}"
                )
            ))
            return findings
        
        # Check encryption algorithm
        sse_algorithm = encryption.get("sse_algorithm", "").lower()
        
        if not sse_algorithm:
            findings.append(Finding(
                severity=Severity.HIGH,
                title=f"S3 bucket '{bucket_name}' has invalid encryption configuration",
                description=(
                    f"The S3 bucket '{bucket_name}' has an encryption configuration but no "
                    f"sse_algorithm specified. Encryption will not be applied."
                ),
                resource_address=f"aws_s3_bucket.{bucket_name}",
                remediation=(
                    "Specify a valid sse_algorithm (AES256 or aws:kms) in the encryption configuration."
                )
            ))
        elif sse_algorithm not in ["aes256", "aws:kms"]:
            findings.append(Finding(
                severity=Severity.HIGH,
                title=f"S3 bucket '{bucket_name}' has unsupported encryption algorithm",
                description=(
                    f"The S3 bucket '{bucket_name}' specifies an unsupported encryption algorithm: "
                    f"'{sse_algorithm}'. Only AES256 and aws:kms are supported."
                ),
                resource_address=f"aws_s3_bucket.{bucket_name}",
                remediation=(
                    "Use either 'AES256' for S3-managed encryption or 'aws:kms' for KMS-managed encryption."
                )
            ))
        else:
            # Valid encryption algorithm
            logger.info(f"S3 bucket '{bucket_name}' has encryption enabled with {sse_algorithm}")
            
            # If using KMS, check if key ID is provided (informational)
            if sse_algorithm == "aws:kms":
                kms_key_id = encryption.get("kms_master_key_id", "")
                if not kms_key_id:
                    findings.append(Finding(
                        severity=Severity.LOW,
                        title=f"S3 bucket '{bucket_name}' uses default KMS key",
                        description=(
                            f"The S3 bucket '{bucket_name}' is configured to use KMS encryption "
                            f"but no specific KMS key ID is provided. The default AWS-managed key "
                            f"(aws/s3) will be used."
                        ),
                        resource_address=f"aws_s3_bucket.{bucket_name}",
                        remediation=(
                            "Consider specifying a customer-managed KMS key for better control over "
                            "encryption key management and rotation policies."
                        )
                    ))
        
        return findings
