import json
import asyncio
from call_gemini import call_llm

REFERENCE_IMAGE_PATH = "reference_photo.jpg"

PROMPT = """
You are an expert telecom infrastructure audit assistant specialized in computer vision and asset verification. 

 Task Overview
Your task is to analyze a set of target site photographs and determine whether an existing GPS module is present. To assist you, a reference image of the specific GPS module has been provided.

 Inputs Provided
1. **Reference Image:** [Label: "Reference Photo"] - This image shows the exact type, shape, color, and form factor of the GPS module you are looking for.
2. **Target Site Images:** [Label: "Site Photo 1", "Site Photo 2", etc.] - The actual field photographs of the telecom site that you need to audit.

 Execution Steps
1. **Analyze the Reference:** Closely examine the "Reference Photo". Note the key visual identifiers of the GPS module: its geometric shape (e.g., dome, puck, rectangular block), color, typical mounting bracket, and texture.
2. **Scan the Target Images:** Systematically scan all provided "Site Photos". Look at antenna headframes, platform railings, equipment racks, and pole tops where a GPS module is typically mounted.
3. **Verify and Cross-Reference:** Compare any candidate objects found in the site photos against the visual features of the reference GPS. Account for different angles, distances, lighting conditions, or minor shadows.
4. **Determine Presence:** 
   - If you find a matching GPS module in *any* of the target site photos, set the conclusion to `true`.
   - If you have scanned all photos thoroughly and no matching GPS module is visible, set the conclusion to `false`.

 Output Format
You must return your analysis strictly in JSON format. Do not include any conversational filler, markdown formatting outside of the json block, or extra text. 

```json
{
  "gps_detected": true/false,
  "reasoning": "A concise explanation of where the GPS was spotted (e.g., 'Detected on the sector A antenna rail matching the reference dome shape') or why it was marked false (e.g., 'Scanned all headframes and poles; no matching GPS module found')."
}
"""


async def analyze_gps_presence(site_image_paths: list[str]):
    """
    Analyzes site photos to detect GPS module using reference image.
    
    Args:
        site_image_paths (list[str]): List of paths to site photographs.
    
    Returns:
        dict: {'gps_detected': bool, 'reasoning': str}
    """
    try:
        # Combine reference image + all site images
        all_images = [REFERENCE_IMAGE_PATH] + site_image_paths

        # Call Gemini LLM
        response = await call_llm(PROMPT, image_paths=all_images)

        # Extract text response
        text = response["candidates"][0]["content"]["parts"][0]["text"].strip()

        # Clean markdown and extract JSON
        text = re.sub(r'```json\s*|\s*```', '', text).strip()

        # Parse JSON
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = json.loads(text)

        return {
            "gps_detected": result.get("gps_detected", False),
            "reasoning": result.get("reasoning", "No reasoning provided.")
        }

    except Exception as e:
        return {
            "gps_detected": False,
            "reasoning": f"Analysis failed: {str(e)}"
        }