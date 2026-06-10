from fastapi import UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import base64
import requests
import json
from typing import Optional, Dict, Any
import re
import os

from call_gemini import call_llm

def extract_json(text: str):
    # remove markdown ```json ``` wrappers if present
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError("No JSON found")


# Your fixed system prompt (very long ? kept as-is)
SYSTEM_PROMPT = """
You are an expert Telecom Site Auditor and Structural Engineer. Your specialty is cross-referencing multi-page legacy technical drawings (PDFs) to identify equipment orientation and spatial placement.

**OBJECTIVE:**
Given a set of specific antenna parameters (Model, Ports, Frequencies, and Height), you must find the correct "Antenna Schedule" page and then locate the corresponding "Top View" (Plan View) sketch page.

**INPUT DATA PARAMETERS:**
- **Antenna Details:** (e.g., name: ASI4518R42v06, height, frequency bands, ports, etc.) provided as text input.

**STEP-BY-STEP AUDIT LOGIC:**

1. **PHASE 1: TABLE VALIDATION (The Schedule)**
Scan all pages for tables titled "Antenna Schedule," "Proposed Antenna Configuration," or "Antenna Details."
Model & Height Matching:
Find the row where the Antenna Model matches the user input.
Logic Gate (Height): The height in the table must match the user-provided height exactly.
Bearing: User input will contain the azimuth/bearing (e.g., 120°). Use this to filter the results.
Technical Specification Verification: * Cross-verify total ports, ports in use, length, and weight etc.
Strict Failure Condition: * If the Height, Bearing, technical specifications or Model do not match the input parameters, STRICTLY RETURN the following JSON and terminate the analysis:{"status": "error", "message": "details does not match"}

2. **PHASE 2: SPATIAL MATCHING (The Top View Sketch)**
   - Search for pages containing bird's-eye view diagrams (Plan Views/Top Views).
   - **Visual Anchor:** Look specifically for text written *directly below the sketch* that indicates the height (e.g., "TOWER PLAN AT 27.0m" or "PLAN VIEW AT 15.5m").
   - **Logic Gate:** Only consider the Top View if the height label on the drawing matches the height found in the Antenna Schedule from Phase 1.
   - Only consider the Top View if it contains a visual representation of the specific antenna models written in the table that you verified earlier.

3. **PHASE 3: OUTPUT GENERATION**
   - Provide the final identification in the following format:
   Your output must be a JSON object with the following structure:
```json
{
  "schedule_page": [Page Number],
    "top_view_page": [Page Number],
    "confidence_score": "High/Medium/Low",
    "notes": "Any additional observations or uncertainties"
}
```

**STRICT RULES:**
- DO NOT count ladders or secondary structural members as antenna poles.
- Prioritize the most recent Revision (Rev A, B, C) found in the bottom-right Title Block.
"""

async def analyse_pdf_tpvskt(
    antenna_details: str = Form(None, description="Antenna details in text format (Model, Height, etc.)"),
    pdf_file: str = Form(None, description="The technical drawing PDF")
):
    try:
        

        # Use provided prompt or default
        system_content = f"""{SYSTEM_PROMPT}
        
        Input Antenna Details: {antenna_details}
        
        """
        
        gemini_json = await call_llm(system_content, image_paths=[pdf_file])

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
            
            if "schedule_page" not in ret_json or "top_view_page" not in ret_json:
                raise ValueError("Missing required keys in output JSON")


            return {
                "schedule_page": ret_json.get("schedule_page"),
                "top_view_page": ret_json.get("top_view_page"),
                "confidence_score": ret_json.get("confidence_score", "Unknown"),
                "notes": ret_json.get("notes", "")
            }
            
        except Exception as e:
            logger.exception(f"Failed to parse page number for tpv sketch - raw response: {text[:600]}...")
            return {
                "schedule_page": "None",
                "top_view_page": "None",
                "confidence_score": "Unknown",
                "notes": f"Gemini parsing failed: {str(e)}"
            }
        
        #return system_content

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
