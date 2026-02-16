"""
Output formatter for Terraform Run Task analysis results.

This module provides markdown formatting with emojis, tables, and structured output
for security findings, cost analysis, and operational recommendations.
"""

from typing import List, Dict, Optional, Any

try:
    from ..models.tool_models import Finding, Severity
except ImportError:
    from models.tool_models import Finding, Severity


class OutputFormatter:
    """
    Formats analysis findings as markdown with emojis and tables.
    
    Features:
    - Emoji indicators for severity levels (🔴 Critical, 🟡 Warning, 🟢 OK, 💰 Cost)
    - Grouped findings by category (Security, Cost, Operations)
    - Formatted tables for cost analysis
    - Output length limiting (9000 characters per section)
    - Prioritizes critical findings when truncating
    """
    
    # Emoji mappings for severity levels
    SEVERITY_EMOJIS = {
        Severity.CRITICAL: "🔴",
        Severity.HIGH: "🟠",
        Severity.MEDIUM: "🟡",
        Severity.LOW: "🟢"
    }
    
    # Maximum characters per section before truncation
    MAX_SECTION_LENGTH = 9000
    
    def __init__(self):
        """Initialize the output formatter."""
        pass
    
    def format(self, findings: List[Finding], cost_analysis: Optional[Dict[str, Any]] = None) -> str:
        """
        Format findings and cost analysis as markdown.
        
        Args:
            findings: List of Finding objects from tool executions
            cost_analysis: Optional dictionary with cost impact data
            
        Returns:
            Formatted markdown string with emojis, tables, and structured output
        """
        output_parts = []
        
        # Header
        output_parts.append("## 🔍 Analysis Summary\n")
        
        # Group findings by category
        security_findings = self._filter_by_category(findings, ["security", "compliance"])
        cost_findings = self._filter_by_category(findings, ["cost"])
        operational_findings = self._filter_by_category(findings, ["operations", "operational", "performance"])
        
        # Security findings section
        if security_findings:
            security_section = self._format_security_section(security_findings)
            output_parts.append(security_section)
        
        # Cost analysis section
        if cost_analysis or cost_findings:
            cost_section = self._format_cost_section(cost_findings, cost_analysis)
            output_parts.append(cost_section)
        
        # Operational findings section
        if operational_findings:
            ops_section = self._format_operational_section(operational_findings)
            output_parts.append(ops_section)
        
        # Recommendations section (if we have any findings)
        if findings:
            recommendations_section = self._format_recommendations_section(findings)
            output_parts.append(recommendations_section)
        
        # If no findings at all, add a positive message
        if not findings and not cost_analysis:
            output_parts.append("\n### 🟢 All Clear\n\n")
            output_parts.append("No security, cost, or operational issues detected in this Terraform plan.\n")
        
        # Join all parts and apply length limiting
        full_output = "\n".join(output_parts)
        return self._apply_length_limit(full_output, findings)
    
    def _filter_by_category(self, findings: List[Finding], categories: List[str]) -> List[Finding]:
        """
        Filter findings by category keywords in title or description.
        
        Args:
            findings: List of findings to filter
            categories: List of category keywords to match
            
        Returns:
            Filtered list of findings matching any category
        """
        filtered = []
        for finding in findings:
            text = f"{finding.title} {finding.description}".lower()
            if any(cat.lower() in text for cat in categories):
                filtered.append(finding)
        return filtered
    
    def _format_security_section(self, findings: List[Finding]) -> str:
        """Format security findings section with severity-based grouping."""
        section = ["\n### 🚨 Security Findings\n"]
        
        # Sort by severity (critical first)
        sorted_findings = sorted(findings, key=lambda f: self._severity_order(f.severity))
        
        for finding in sorted_findings:
            emoji = self.SEVERITY_EMOJIS.get(finding.severity, "⚪")
            severity_label = finding.severity.value.capitalize()
            
            section.append(f"\n{emoji} **{severity_label}**: {finding.title}\n")
            section.append(f"- **Resource**: `{finding.resource_address}`\n")
            section.append(f"- **Issue**: {finding.description}\n")
            section.append(f"- **Remediation**: {finding.remediation}\n")
        
        return "".join(section)
    
    def _format_cost_section(self, findings: List[Finding], cost_analysis: Optional[Dict[str, Any]]) -> str:
        """Format cost analysis section with tables and findings."""
        section = ["\n### 💰 Cost Analysis\n"]
        
        # Add cost table if analysis data is provided
        if cost_analysis:
            section.append(self._format_cost_table(cost_analysis))
        
        # Add cost-related findings
        if findings:
            section.append("\n**Cost Findings:**\n")
            for finding in findings:
                emoji = self.SEVERITY_EMOJIS.get(finding.severity, "⚪")
                section.append(f"\n{emoji} {finding.title}\n")
                section.append(f"- **Resource**: `{finding.resource_address}`\n")
                section.append(f"- **Impact**: {finding.description}\n")
                section.append(f"- **Recommendation**: {finding.remediation}\n")
        
        return "".join(section)
    
    def _format_cost_table(self, cost_analysis: Dict[str, Any]) -> str:
        """Format cost analysis data as a markdown table."""
        table = ["\n| Resource | Current Cost | New Cost | Change |\n"]
        table.append("|----------|-------------|----------|--------|\n")
        
        resources = cost_analysis.get("resources", [])
        for resource in resources:
            resource_name = resource.get("name", "Unknown")
            current_cost = resource.get("current_cost", 0.0)
            new_cost = resource.get("new_cost", 0.0)
            change = new_cost - current_cost
            
            # Format costs
            current_str = f"${current_cost:.2f}/mo" if current_cost > 0 else "$0.00"
            new_str = f"${new_cost:.2f}/mo"
            
            # Format change with emoji indicator
            if change > 0:
                change_str = f"+${change:.2f} 🔴"
            elif change < 0:
                change_str = f"-${abs(change):.2f} 🟢"
            else:
                change_str = "$0.00"
            
            table.append(f"| {resource_name} | {current_str} | {new_str} | {change_str} |\n")
        
        # Add total row
        total_current = cost_analysis.get("total_current_cost", 0.0)
        total_new = cost_analysis.get("total_new_cost", 0.0)
        total_change = total_new - total_current
        
        current_total_str = f"${total_current:.2f}/mo" if total_current > 0 else "$0.00"
        new_total_str = f"${total_new:.2f}/mo"
        
        if total_change > 0:
            change_total_str = f"+${total_change:.2f}"
        elif total_change < 0:
            change_total_str = f"-${abs(total_change):.2f}"
        else:
            change_total_str = "$0.00"
        
        table.append(f"| **Total** | **{current_total_str}** | **{new_total_str}** | **{change_total_str}** |\n")
        
        return "".join(table)
    
    def _format_operational_section(self, findings: List[Finding]) -> str:
        """Format operational findings section."""
        section = ["\n### ⚙️ Operational Findings\n"]
        
        for finding in findings:
            emoji = self.SEVERITY_EMOJIS.get(finding.severity, "⚪")
            section.append(f"\n{emoji} {finding.title}\n")
            section.append(f"- **Resource**: `{finding.resource_address}`\n")
            section.append(f"- **Issue**: {finding.description}\n")
            section.append(f"- **Recommendation**: {finding.remediation}\n")
        
        return "".join(section)
    
    def _format_recommendations_section(self, findings: List[Finding]) -> str:
        """Format recommendations section with key takeaways."""
        section = ["\n### 🟢 Key Recommendations\n"]
        
        # Extract unique recommendations from critical and high severity findings
        critical_high = [f for f in findings if f.severity in [Severity.CRITICAL, Severity.HIGH]]
        
        if critical_high:
            section.append("\n**Priority Actions:**\n")
            for i, finding in enumerate(critical_high[:5], 1):  # Limit to top 5
                section.append(f"{i}. {finding.remediation}\n")
        else:
            section.append("\nNo critical or high-priority actions required. Continue monitoring for best practices.\n")
        
        return "".join(section)
    
    def _apply_length_limit(self, output: str, findings: List[Finding]) -> str:
        """
        Apply length limiting to output, prioritizing critical findings.
        
        Args:
            output: Full formatted output string
            findings: Original findings list for prioritization
            
        Returns:
            Truncated output if necessary, with critical findings preserved
        """
        if len(output) <= self.MAX_SECTION_LENGTH:
            return output
        
        # If output is too long, rebuild with only critical/high findings
        critical_high = sorted(
            [f for f in findings if f.severity in [Severity.CRITICAL, Severity.HIGH]],
            key=lambda f: self._severity_order(f.severity)
        )
        
        truncated_parts = []
        truncated_parts.append("## 🔍 Analysis Summary\n")
        truncated_parts.append("\n⚠️ *Output truncated to show critical and high-priority findings only*\n")
        
        # Add findings one by one until we approach the limit
        current_length = len("".join(truncated_parts))
        included_count = 0
        
        for finding in critical_high:
            # Estimate finding size (conservative)
            finding_text = self._format_single_finding(finding)
            if current_length + len(finding_text) > self.MAX_SECTION_LENGTH - 200:  # Leave room for footer
                break
            
            if included_count == 0:
                truncated_parts.append("\n### 🚨 Priority Findings\n")
            
            truncated_parts.append(finding_text)
            current_length += len(finding_text)
            included_count += 1
        
        omitted = len(findings) - included_count
        if omitted > 0:
            truncated_parts.append(f"\n\n*{omitted} additional findings omitted due to length constraints*\n")
        
        return "".join(truncated_parts)
    
    def _format_single_finding(self, finding: Finding) -> str:
        """Format a single finding for display."""
        emoji = self.SEVERITY_EMOJIS.get(finding.severity, "⚪")
        severity_label = finding.severity.value.capitalize()
        
        parts = [f"\n{emoji} **{severity_label}**: {finding.title}\n"]
        parts.append(f"- **Resource**: `{finding.resource_address}`\n")
        parts.append(f"- **Issue**: {finding.description}\n")
        parts.append(f"- **Remediation**: {finding.remediation}\n")
        
        return "".join(parts)
    
    def _severity_order(self, severity: Severity) -> int:
        """Return numeric order for severity sorting (lower = more severe)."""
        order = {
            Severity.CRITICAL: 0,
            Severity.HIGH: 1,
            Severity.MEDIUM: 2,
            Severity.LOW: 3
        }
        return order.get(severity, 99)
