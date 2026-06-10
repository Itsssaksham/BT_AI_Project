import requests
from typing import Optional

async def get_prompt_by_code(code: str) -> Optional[str]:
    """
    Fetches a telecom RF audit prompt by its unique identifier code.
    
    :param code: The unique prompt identifier (e.g., 'PROMPT_001')
    :return: The prompt text string or None if an error occurs
    """
    base_url = "https://telecom-design-api.thebetalabs.com/survey-inventory-manager/prompt/v1/get-by-code"
    
    # Define query parameters
    params = {
        "code": code
    }
    
    try:
        # Make the GET request
        response = requests.get(base_url, params=params)
        
        # Raise an exception for bad status codes (4xx, 5xx)
        response.raise_for_status()
        
        # Parse JSON response
        json_data = response.json()
        
        # Safely extract the prompt string
        prompt_text = json_data.get("data", {}).get("prompt")
        
        if prompt_text:
            return prompt_text
        else:
            print("Error: Prompt text not found in response structure.")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching the prompt: {e}")
        return None