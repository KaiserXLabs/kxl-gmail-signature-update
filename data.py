import re
from typing import Dict, Any, List, Optional, Union

# Constants for company information
COMPANY_NAME = "Kaiser X Labs"
COMPANY_WEBSITE = "http://www.kaiser-x.com/"

# Template replacement operators
NORMAL_REPLACEMENT = "normal"
CUSTOM_PARAGRAPH_WITH_VARIABLE = "customParagraphWithVariable"
CUSTOM_PARAGRAPH_WITHOUT_VARIABLE = "customParagraphWithoutVariable"

def replace_template_variable(text: str, keyword: str, operator: str, data: Dict[str, Any]) -> str:
    """
    Replace template variables in text based on the specified operator and data.
    
    Args:
        text: The template text containing variables to replace
        keyword: The variable keyword to replace
        operator: The replacement operator type (normal, customParagraphWithVariable, customParagraphWithoutVariable)
        data: Dictionary containing the data for replacements
        
    Returns:
        The text with replacements applied
    """
    if operator == NORMAL_REPLACEMENT:
        return text.replace(f"{{{keyword}}}", str(data.get(keyword, "")))
    elif operator == CUSTOM_PARAGRAPH_WITH_VARIABLE:
        if data.get(keyword):
            text = remove_tags(text, keyword)
            return text.replace(f"{{{keyword}}}", str(data[keyword]))
        else:
            return remove_everything_between_tags(text, keyword)
    elif operator == CUSTOM_PARAGRAPH_WITHOUT_VARIABLE:
        if data.get(keyword) is True:
            return remove_tags(text, keyword)
        else:
            return remove_everything_between_tags(text, keyword)
    
    # Return original text if operator not recognized
    return text

def remove_tags(text: str, keyword: str) -> str:
    """
    Remove opening and closing tags for a specific keyword from the text.
    
    Args:
        text: The text containing tags
        keyword: The keyword for which to remove tags
        
    Returns:
        Text with tags removed
    """
    text = text.replace(f"{{{keyword}/}}", "")
    text = text.replace(f"{{/{keyword}}}", "")
    return text

def remove_everything_between_tags(text: str, keyword: str) -> str:
    """
    Remove everything between opening and closing tags for a specific keyword.
    
    Args:
        text: The text containing tagged sections
        keyword: The keyword for which to remove content between tags
        
    Returns:
        Text with tagged sections removed
    """
    pattern = re.compile(rf"{{{keyword}/}}.*?{{/{keyword}}}", re.DOTALL)
    return re.sub(pattern, "", text)

def process_user_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process raw user data from Google Directory API into a format suitable for signature generation.
    
    Args:
        data: Raw user data from Google Directory API
        
    Returns:
        Processed user data dictionary with extracted and formatted information
    """
    # Check if user is a technical account
    technical_user = data.get("orgUnitPath") == "/Orga Accounts"
    
    # Extract basic information
    email = data.get("primaryEmail", "")
    first_name = data.get("name", {}).get("givenName", "")
    last_name = data.get("name", {}).get("familyName", "")
    
    # Extract phone numbers
    phone_candidates = data.get("phones", [])
    phone = ""
    mobile = ""
    for phone_entry in phone_candidates:
        if phone_entry.get("type") == "work":
            phone = phone_entry.get("value", "")
        elif phone_entry.get("type") == "mobile":
            mobile = phone_entry.get("value", "")
    
    # Extract address
    address = ""
    address_candidates = data.get("addresses", [])
    for address_entry in address_candidates:
        if address_entry.get("type") == "work":
            address = address_entry.get("formatted", "")
    
    # Return minimal data for technical users
    if technical_user:
        return {
            "technicalUser": True,
            "email": email,
            "lastName": last_name,
            "address": address,
            "phone": phone,
        }
    
    # Extract job title and department
    jobtitle = ""
    department = ""
    organizations = data.get("organizations", [])
    if organizations:
        jobtitle = organizations[0].get("title", "")
        department = organizations[0].get("department", "")
    
    # Extract custom schema information
    custom_schemas = data.get("customSchemas", {})
    personal_information = custom_schemas.get("Personal_Information", {})
    contractual_information = custom_schemas.get("Contractual_Information", {})

    pronouns = personal_information.get("Pronouns", "")
    gerne_per_du = personal_information.get("GernePerDu", "") == "yes"
    conditional_line_break = not (pronouns == "" and gerne_per_du == False)
    management_role = contractual_information.get("Management_Role", "")

    return {
        "technicalUser": False,
        "email": email,
        "firstName": first_name,
        "lastName": last_name,
        "jobtitle": jobtitle,
        "address": address,
        "department": department,
        "phone": phone,
        "mobile": mobile,
        "pronouns": pronouns,
        "gernePerDu": gerne_per_du,
        "conditionalLineBreak": conditional_line_break,
        "managementRole": management_role,
    }

def build_signature(html_template: str, employee_data: Dict[str, Any]) -> str:
    """
    Build an email signature by replacing template variables with employee data.
    
    Args:
        html_template: HTML template containing variables to be replaced
        employee_data: Dictionary containing employee data for replacements
        
    Returns:
        Completed HTML signature with all variables replaced
    """
    # Common replacements for both technical and regular users
    replacements = [
        ("lastName", NORMAL_REPLACEMENT),
        ("address", NORMAL_REPLACEMENT),
        ("phone", CUSTOM_PARAGRAPH_WITH_VARIABLE),
        ("email", NORMAL_REPLACEMENT),
    ]
    
    # Add technical user specific or regular user specific replacements
    if employee_data.get("technicalUser"):
        # No additional replacements for technical users
        pass
    else:
        # Additional replacements for regular users
        additional_replacements = [
            ("firstName", NORMAL_REPLACEMENT),
            ("jobtitle", NORMAL_REPLACEMENT),
            ("managementRole", CUSTOM_PARAGRAPH_WITH_VARIABLE),
            ("pronouns", CUSTOM_PARAGRAPH_WITH_VARIABLE),
            ("gernePerDu", CUSTOM_PARAGRAPH_WITHOUT_VARIABLE),
            ("conditionalLineBreak", CUSTOM_PARAGRAPH_WITHOUT_VARIABLE),
            ("mobile", CUSTOM_PARAGRAPH_WITH_VARIABLE),
        ]
        replacements.extend(additional_replacements)

    # Apply all replacements
    for keyword, operator in replacements:
        html_template = replace_template_variable(html_template, keyword, operator, employee_data)
    
    # Replace company constants
    html_template = html_template.replace("{company}", COMPANY_NAME)
    html_template = html_template.replace("{web}", COMPANY_WEBSITE)
    
    return html_template
