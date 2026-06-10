import json
import asyncio
import re
from call_gemini import call_llm

from fastapi import UploadFile, File, Form, HTTPException

import httpx

# Your fixed system prompt (very long ? kept as-is)
SYSTEM_PROMPT = """

You are an expert telecom structural engineer and document parser. Your task is to analyze the provided telecom site documentation (including tower sketches, headframe drawings, antenna loading schedules, and structural analysis documents) and extract the specifications of all MICROWAVE DISHES.

### Extraction Instructions:
1. Identify the LATEST sketches, structural modifications, or loading tables in the document. Ignore superseded or historical equipment configurations if a "Proposed" or "Final" state is explicitly outlined.
2. Locate the microwave dishes on the tower or headframe drawings and cross-reference them with the text-based equipment schedules.
3. For EVERY unique microwave dish identified, extract the required attributes. Do not mistake standard panel/cellular antennas for microwave dishes (microwave dishes are typically circular or parabolic shrouds).
4. If the table has missing values for any dish, do not infer or guess. Look for the sketch that can provide the missing information.
5. Only consider dishes that are explicitly listed for BT or EE or H3G.
### Target Attributes to Extract:
- number_of_microwave_dish: The grand total count of microwave dishes on the structure.
- diameter: The size/diameter of the dish (look for expressions like 2ft, 4ft, 0.6m, 1.2m, etc.). Convert to feet or meters exactly as listed in the text, or record the raw text string if mixed.
- azimuth: The orientation angle in degrees (0° to 360°). If omitted or labeled as "Omni/TBD", mark it null.
- height: The centerline radiation center line (RAD center) or tip mounting height relative to ground level (AGL - Above Ground Level).

### Constraints:
- Do not guess or assume values. If a value cannot be found visually or in text for a dish, return null for that specific key.
- Provide the output EXCLUSIVELY as a valid JSON object. Do not include any markdown fences (like ```json), conversational text, explanations, or leading/trailing characters.

### Output JSON Format:
{
  "site_summary": {
    "number_of_microwave_dish": 0
  },
  "microwave_dishes": [
    {
      "dish_index": 1,
      "diameter_or_size": "string or null",
      "azimuth_degrees": 0,
      "height_agl_ft_or_m": "string or null"
    }
  ]
}

"""

Comp_prompt = """ 
# Purpose
You are an expert Telecom Structural Audit Agent. Your task is to reconcile microwave dish data extracted from a legacy PDF document against real-time site survey data, detect mismatches, and output a structured analysis strictly in JSON format.

# Inputs
You will be provided with two sets of data:
1. **Legacy PDF Data**: Contains the historical records of the microwave dishes, including `Height`, `Azimuth`, `Diameter`, and total `Count`.
2. **Site Survey Data**: Contains the live, physically detected microwave dishes on-site, including `Height` and `Azimuth` for each dish.

# Matching Logic & Tolerance Rules
* **Count Match**: Compare the total number of dishes found in the Site Survey against the total number listed in the Legacy PDF.
* **Coordinate Matching**: Match a Site Survey dish to a Legacy PDF dish if their `Height` and `Azimuth` values are reasonably close. 
  * *Note on Tolerances*: Allow a minor real-world tolerance for physical measurements (e.g., ±0.5 feet/meters for height, and ±1 to 2 degrees for azimuth due to field calculation variances).
* **Diameter Assignment**: Map the correct `Diameter` from the matched Legacy PDF dish onto the corresponding Site Survey dish. If a site survey dish cannot be matched to any legacy record, set the diameter to null or "Unknown".

# Output Filtering Constraints (Strict)
* The `site_survey_dishes` array in the JSON output **must exclusively contain dishes that were present in the live Site Survey input data**. 
* Do not append extra rows for unmatched historical dishes from the Legacy PDF into this array. 
* The purpose of this array is to enrich the freshly detected site data with legacy diameters, not to inventory the legacy file.

# Output Requirement
Return ONLY a valid JSON object. Do not include any markdown formatting wrappers (like ```json), introduction, or conversational filler. The response must be directly parsable.

## JSON Schema
{
  "data_match": boolean, // true ONLY if total count matches AND every site survey dish maps to a legacy record
  "executive_summary": "string", // A short, concise summary highlighting similarities, count discrepancies, or specific dish variances.
  "site_survey_dishes": [
    {
      "dish_number": integer,
      "height": "string or number", // Directly from Site Survey input
      "azimuth": "string or number", // Directly from Site Survey input
      "diameter": "string or number or null" // Enriched from Legacy PDF; null if no match found
    }
  ]
}

# Execution
Analyze the inputs provided below and generate the JSON response conforming strictly to the schema and filtering constraints above.

"""

async def analyse_legacy_mw(legacy_pdf: str = Form(None, description="The technical drawing PDF"), existing_dishes: str = Form(..., description="Raw input text/string of existing dishes (e.g., height, azimuth specs)")):
    """
    Analyzes legacy telecom PDF for microwave dishes.
    """
    try:
        
        
        gemini_json = await call_llm(SYSTEM_PROMPT, image_paths=[legacy_pdf])

        try:
        # ── Extract raw text ───────────────────────────────────────
            text = (
                gemini_json["candidates"][0]["content"]["parts"][0]["text"]
                .strip()
            )

            # ── Aggressive cleaning ────────────────────────────────────
            # Remove all common markdown code fences (multiple variants)
            text = re.sub(r'^(```(?:json)?\s*|\s*```json\s*)', '', text, flags=re.IGNORECASE | re.MULTILINE)
            text = re.sub(r'(\s*```)$', '', text, flags=re.MULTILINE)

            # Remove any leading/trailing backticks that survived
            text = text.strip('` \n\r')

            # Remove markdown bold/italic that sometimes leaks in
            text = re.sub(r'\*+([^*]+)\*+', r'\1', text)

            # Final strip
            text = text.strip()

            if not text:
                raise ValueError("Empty text after cleaning")

            # ── Parse ──────────────────────────────────────────────────
            ret_json = json.loads(text)
            
            if "site_summary" not in ret_json or "microwave_dishes" not in ret_json:
                raise ValueError("Missing required keys in output JSON")


            c_p = f"""
            {Comp_prompt}

            Legacy PDF data:
            {ret_json}

            Input microwave details to compare against:
            {existing_dishes}
             """

            res = await call_llm(c_p)


            return res
            
        except Exception as e:
            return {
                "site": None,
                "microwave_dishes": [],
                "error": f"Error parsing LLM output: {str(e)}"
            }
        
        #return system_content

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))