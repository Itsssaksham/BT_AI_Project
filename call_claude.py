from anthropic import AsyncAnthropic
from typing import List, Tuple
import base64

anthropic_client = AsyncAnthropic(
    api_key="",
    timeout=300.0
)

# Define the exact beta version string required by the SDK
FILES_API_BETA = ["files-api-2025-04-14"]

async def call_claude(
    meta_prompt: str, 
    files_data: List[Tuple[str, bytes, str]] = None
) -> str:
    """
    Sends a request to Claude with an optional list of files (PDFs or Images).
    
    :param meta_prompt: The core text prompt instruction.
    :param files_data: A list of tuples containing (filename, file_bytes, media_type).
    """
    if files_data is None:
        files_data = []
    
    message_content = []
    has_pdf = False

    # 1. Process files dynamically
    for filename, file_bytes, media_type in files_data:
        
        # Handle PDFs via the Files API
        if media_type == "application/pdf":
            has_pdf = True
            uploaded_file = await anthropic_client.beta.files.upload(
                file=(filename, file_bytes, "application/pdf"),
                betas=FILES_API_BETA
            )
            message_content.append({
                "type": "document",
                "source": {
                    "type": "file",
                    "file_id": uploaded_file.id
                },
                "title": filename
            })
            
        # Handle Images (PNG, JPG, JPEG, WebP) inline
        elif media_type in ["image/png", "image/jpeg", "image/webp"]:
            base64_image = base64.b64encode(file_bytes).decode("utf-8")
            message_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64_image
                }
            })

    # 2. Append the main prompt text
    message_content.append({
        "type": "text",
        "text": meta_prompt
    })
    
    # 3. Prepare call parameters (This fixes the 'NoneType' error)
    params = {
        "model": "claude-opus-4-8",
        "max_tokens": 60000,
        "messages": [
            {
                "role": "user",
                "content": message_content
            }
        ],
        # Swapping to adaptive mode removes the deprecation warning entirely
        "thinking": {
            "type": "adaptive" 
        },
        "output_config": {
            "effort": "medium"  # Uses the native reasoning engine efficiently
        }
    }

    # Only include betas when using PDFs (important!)
    if has_pdf:
        params["betas"] = FILES_API_BETA

    # 4. Call Claude

    response = await anthropic_client.beta.messages.create(**params)
    
    # 5. FIXED HERE: Dynamically find and extract the text block block


    return response
    
    raise ValueError("The API response did not contain a valid text block.")