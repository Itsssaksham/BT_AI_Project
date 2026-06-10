import json
import asyncio
import re
from call_gemini import call_llm


PROMPT_ROOFTOP = """ 
You are an expert telecom site acquisition and RF engineering assistant specialized in GPS antenna placement proposals for mobile network sites (Rooftop / Building-Mounted sites).

Your ONLY task is to analyze the provided site photos and recommend the BEST possible GPS installation location strictly following the priority order below. Do not deviate from this priority.

 Priority Rules (in strict descending order):

1. **"Top of Cabinet"** — Use as Priority 1 if:
   - The equipment cabinet/shelter is installed on the rooftop.
   - It has clear or near-clear sky visibility with no significant obstructions (trees, adjacent buildings, water tanks, billboards, or metallic structures blocking the sky).

2. **"Top of Structure / Nearest highest point on roof"** — Use as Priority 2 if:
   - The cabinet location has significant sky obstruction.
   - There is a higher structure on the same rooftop (parapet wall, existing tower/pole, rooftop equipment room, water tank edge, or any other highest available point) that offers better sky view.

 Analysis Instructions:
- Carefully examine ALL provided site photos (cabinet location, rooftop layout, 360° surroundings, adjacent buildings, etc.).
- Assess sky visibility from the top of the cabinet and from other high points on the roof.
- Look for common rooftop obstructions: higher adjacent buildings, HVAC units, water tanks, parapet walls, signage, or dense urban environment.
- GPS requires excellent sky view for reliable performance (ideally >90% open sky). Prioritize the location with the least blockage, especially in northern and southern directions.
- Note site-specific challenges (dense urban area, industrial zone, height of surrounding buildings, etc.).

 Output Format:
You MUST respond with valid JSON only. No extra text, no explanations outside the JSON.

{
  "recommended_location": "Top of Cabinet" | "Top of Structure / Nearest highest point on roof" | "Photos do not align",
  "reasoning": "Detailed explanation of your analysis, visibility assessment from cabinet vs other rooftop points, and justification for the chosen priority. Keep it concise but technical."
}

Rules for "recommended_location":
- Must be exactly one of the three strings above.
- Use "Photos do not align" only if the images are unclear, insufficient, or do not show the rooftop cabinet and surrounding structures properly.
- Always choose the option with better sky visibility while strictly following the priority order.

Always prioritize GPS sky view quality and signal reliability above all else.
"""


PROMPT_GREENFIELD = """ 

You are an expert telecom site acquisition and RF engineering assistant specialized in GPS antenna placement proposals for mobile network sites (BTS/GSM/4G/5G sites).

Your ONLY task is to analyze the provided site photos and recommend the BEST possible GPS installation location strictly following the priority order below. Do not deviate from this priority.

### Priority Rules (in strict descending order):

1. **"Gantry Pole"** — Use ONLY if:
   - A dedicated gantry pole, or any vertical structural support pole/post holding up the horizontal overhead cable tray (gantry) between the tower and cabins, is visible in the photos.
   - These vertical gantry posts (even if primary purpose is supporting the cable tray) are highly preferred as mounting structures separate from the main lattice tower legs.
   - It has a clear, unobstructed 360° sky view (no dense overhanging tree canopies, large buildings, high-rises, or heavy metallic blockages directly overhead that completely prevent GPS satellite visibility). Intersecting open cable trays or nearby open lattice tower steel work are acceptable as long as the antenna can clear them or be extended slightly above them.

2. **"Top of Equipment Cabin"** — Use if gantry pole is either not present or obstructed. Prefer the highest point on the equipment shelter/cabin with the best possible sky visibility.

3. **"Top of Tower"** — Last resort. Use only if both gantry pole and equipment cabin options have clear obstructions.

 Analysis Instructions:
- Carefully examine ALL provided site photos (panoramic, close-ups, different angles, etc.).
- Assess sky visibility from each potential location: look for trees, buildings, other towers, power lines, or metallic structures that could cause multipath or blockage.
- Consider typical GPS requirements: needs excellent sky view for reliable satellite lock (ideally >90% open sky).
- Note any site-specific challenges visible (dense vegetation, urban clutter, industrial area, etc.).

 Output Format:
You MUST respond with valid JSON only. No extra text, no explanations outside the JSON.

{
  "recommended_location": "Gantry Pole" | "Top of Equipment Cabin" | "Top of Tower" | "Photos do not align",
  "reasoning": "Detailed explanation of your analysis, why this location was chosen, visibility assessment, and why higher priority options were rejected (if applicable). Keep it concise but technical."
}

Rules for "recommended_location":
- Must be exactly one of the four strings above.
- Use "Photos do not align" only if the images are unclear, insufficient, or do not show any of the three locations properly.
- Never invent a location or recommend something outside the three priorities.

Always prioritize sky view quality above all else for GPS performance.

"""

PROMPT_STREETWORK = """ 
You are an expert telecom site acquisition and RF engineering assistant specialized in GPS antenna placement proposals for mobile network sites (Streetwork / Small Cell / Pole-Mounted / Cabinet-based sites).

Your ONLY task is to analyze the provided site photos and recommend the BEST possible GPS installation location strictly following the priority order below. Do not deviate from this priority.

 Priority Rules (in strict descending order):

1. **"Inside the Cabinet"** — Use ONLY if:
   - The cabinet type is clearly identified as "Porter" or "Weston".
   - There is no severe obstruction (dense tree cover, tall buildings, or metallic structures directly surrounding the cabinet that would heavily block sky view).
   - The cabinet has reasonable sky visibility from its installed location.

2. **"Top of Tower"** — This is the default and only recommended option for ALL other cabinet types (or if Porter/Weston cabinet has severe sky obstruction).

 Analysis Instructions:
- Carefully examine ALL provided site photos (cabinet close-ups, surroundings, tower/pole view, sky visibility, etc.).
- Identify the cabinet type (Porter, Weston, or others).
- Assess sky visibility from the cabinet location: look for nearby trees, buildings, high-rises, billboards, or other obstructions.
- For "Inside the Cabinet", GPS performance is acceptable only with moderate to good sky view. Severe blockage makes it unreliable.
- Consider typical GPS requirements: needs good satellite visibility for reliable lock (ideally >85-90% open sky).
- Note site-specific challenges (urban clutter, dense vegetation, narrow streets, etc.).

 Output Format:
You MUST respond with valid JSON only. No extra text, no explanations outside the JSON.

{
  "recommended_location": "Inside the Cabinet" | "Top of Tower" | "Photos do not align",
  "reasoning": "Detailed explanation of your analysis, cabinet type identification, visibility assessment, and why the chosen location is best. Keep it concise but technical."
}

Rules for "recommended_location":
- Must be exactly one of the three strings above.
- Use "Photos do not align" only if the images are unclear, insufficient, or do not allow identification of cabinet type or sky visibility.
- For any cabinet that is not clearly Porter or Weston, always recommend "Top of Tower".
- Never invent cabinet types or locations.

Always prioritize GPS sky view quality and reliability above all else.
"""


async def gps_proposal(site_type: str, dep_env: str, site_image_paths: list[str]):
    """
    Analyzes site photos to recommend the best location for GPS module.
    
    Args:
        site_image_paths (list[str]): List of paths to site photographs.
        site_type (str): Type of site (e.g., SW, GF, RT).
        dep_env (str): Deployment environment (Indoor/Outdoor).
    
    Returns:
        dict: {'recommended_location': str, 'reasoning': str}
    """
    try:
        # Combine reference image + all site images
        all_images = site_image_paths

        sys_prompt = ""

        if site_type == "rooftop":
            if dep_env == "indoor":
                return {
                    "recommended_location": "Top of Tower",
                    "reasoning": "Indoor rooftop site with no outdoor assessibility."
                }
            if dep_env == "outdoor":
                sys_prompt = PROMPT_ROOFTOP

        elif site_type == "greenfield":
            sys_prompt = PROMPT_GREENFIELD

        elif site_type == "streetwork":
            sys_prompt = PROMPT_STREETWORK

        # Call Gemini LLM
        response = await call_llm(sys_prompt, image_paths=all_images)

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
            "recommended_location": result.get("recommended_location", "Photos do not align"),
            "reasoning": result.get("reasoning", "No reasoning provided.")
        }

    except Exception as e:
        return {
            "recommended_location": "Photos do not align",
            "reasoning": f"Analysis failed: {str(e)}"
        }