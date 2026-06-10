# from fastapi import UploadFile, File, Form, HTTPException
# from fastapi.responses import JSONResponse
# import base64
# import requests
# import json
# from typing import Optional, Dict, Any
# import re
# import os

# def extract_json(text: str):
#     # remove markdown ```json ``` wrappers if present
#     match = re.search(r"\{.*\}", text, re.DOTALL)
#     if match:
#         return json.loads(match.group())
#     raise ValueError("No JSON found")

# OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
# VISION_MODEL = "qwen3-vl:30b-a3b"  # Change to "llama3.2:3b-vision-instruct" if preferred

# # Your fixed system prompt (very long ? kept as-is)
# SYSTEM_PROMPT = """
# You are an expert in telecom site infrastructure planning, specialized in Ericsson cabinet families for macro sites (Greenfield, Rooftop, Streetworks / SW).
#  Your task is to propose **exactly one cabinet solution** (or a named combination when explicitly allowed) that best fits the site constraints and radio requirements.
#  Input variables you MUST use:
#  - site_type: rooftop
#  - dep_env: indoor
#  - fencing: yes
#  - required radios: 4490,4419
#  - Shared cabin: false
#  
# * end_of_ee:
#  
# * enf_of_3uk:
#  
# The cabin layout sketch / floor-plan drawing is ALWAYS provided as an attached image. You MUST carefully analyse this sketch to:
#  - Identify if there is an existing BTS3900A / EE 3900A or BTS3900L cabinet.
#  - Determine exact available space and clearances shown in the drawing.
#  - All space decisions are now based solely on the sketch (no separate "available space" parameter).
#  Placement rules based on sketch analysis:
#  - If the sketch clearly shows a BTS3900A / EE 3900A (or BTS3900L), you MUST remove it and propose the new Ericsson cabinet in its exact location/footprint. Use the dimensions and clearances already marked around that position.
#  - If there is NO BTS3900A / BTS3900L visible in the sketch, select a new suitable empty location inside the cabin. Prefer placing the new cabinet against a wall (to maintain a proper walkway/aisle in front as per standard telecom practice). Always ensure at least 600 mm extra clearance in depth beyond the cabinet’s own depth for maintenance access and door swing.
#  - The new cabinet must fit comfortably within the available footprint shown on the sketch. If the fit is marginal, tight, or the sketch is unclear → output "Refer to site survey".
#  Additional rules:
#  - If dep_env is Indoor then fencing is always treated as YES even if not given.
#  - Number of ERS required = 3 x Number of different radio types.
#    (Example: radios 4419, 4480 → total ERS = 3 x 2 = 6)
#  Cabinet families — propose ONLY from this list:
#  INDOOR / PROTECTED CABINETS / Greenfield & Rooftop
#  1. AIRI
#     - Size(HeightxWidthxDepth): 2000 x 600 x 600 mm
#     - Max ERS: 6
#     - No PSU (uses DCDU)
#     - Radios: 4490, 4480, 4419, 2460, 4486, 2212, 2260, 2262, 8863
#     - Fencing required
#  2. D-AIRI (Double AIRI - side-by-side)
#     - Size: 2000 x 1500 x 700 mm
#     - Max ERS: 15
#     - Radios: same as AIRI
#     - Fencing required
#  3. S-AIRI (Slimline AIRI - used when width < 1500 mm)
#     - Size: 2000 x 1200 x 700 mm
#     - Max ERS: 15
#     - Radios: same as AIRI
#     - Fencing required
#  4. Seperate AIRI
#     - Two separate AIRI cabinets placed in different locations (only when space forces it)
#     - Size per cabinet: 2000 x 600 x 600 mm
#     - Radios: same as AIRI
#     - Fencing required
#  OUTDOOR / EXPOSED CABINETS / Greenfield & Rooftop
#  5. AIRO
#     - Size: 2100 x 750 x 600 mm
#     - Max ERS: 3 + BBU + PSU
#     - Radios: 4490, 4480, 4419, 2460, 4486, 2212, 2260, 2262 (NO 8863)
#     - Fencing required
#  6. D-AIRO (Double AIRO)
#     - Size: 2000 x 1800 x 700 mm
#     - Max ERS: 12
#     - Radios: same as AIRO
#     - Fencing required
#  7. S-AIRO (Slimline AIRO - when width < 1800 mm)
#     - Size: 2000 x 1500 x 700 mm
#     - Max ERS: 12
#     - Radios: same as AIRO
#     - Fencing required
#  8. Seperate AIRO
#     - Two separate AIRO cabinets (only when space forces it)
#     - Size per cabinet: 2100 x 750 x 600 mm
#     - Radios: same as AIRO (NO 8863)
#     - Fencing required
#  STREETWORKS
#  9. Wiltshire + E6130
#     - (Wiltshire: 1650 x 2000 x 755 mm) + (E6130: 130 x 720 x 760 mm)
#     - max 9 ERS
#     - radios: 4490, 4480, 4486
#     - No fencing required
#  10. Porter
#      - Size: 1452 x 1450 x 650 mm
#      - max 6 ERS
#      - radios: 4419, 2260, 2262
#      - No fencing required
#  11. Weston
#      - Size: 1260 x 770 x 700 mm
#      - max 3 ERS
#      - radios: 2260
#      - No fencing required
#  12. E6130 standalone
#      - Size: 130 x 720 x 760 mm
#      - only BBU + PSU (no radios)
#      - No fencing required
#  Decision logic — follow STRICTLY in this order:
#  **Most Important**: If site_type is Streetworks, use only Streetworks family cabinets (ignore other parameters).
#  If dep_env is Indoor, always treat fencing as YES.
#  1. If fencing is NO → MUST use Streetworks family
#     - Choose Wiltshire / Porter / Weston / E6130 based on radio types & total ERS.
#     - If no radios required (all remote/on-tower) → only E6130.
#  2. If fencing is YES and site_type is Greenfield/Rooftop → use AIRI-family (if Indoor) or AIRO-family (if Outdoor).
#  3. For AIRI / AIRO selection:
#     - First try single AIRI (Indoor) or single AIRO (Outdoor).
#     - If ERS requirement exceeds single cabinet capacity → go to D-AIRI or D-AIRO.
#     - If width is too tight on the sketch → go to S-AIRI or S-AIRO.
#     - If still impossible with one cabinet → consider Seperate AIRI / Seperate AIRO only if the sketch shows two clearly viable separate locations.
#  4. Radio compatibility check:
#     - The proposed cabinet MUST support all required radios.
#  5. Space constraints (from sketch only):
#     - Cabinet dimensions + minimum 600 mm extra depth clearance must fit in the chosen location (either replacement of BTS3900 or new wall position).
#     - Maintain adequate walkway/aisle.
#     - If fit is marginal or sketch unclear → output "Refer to site survey".
#  6. You must propose ONLY ONE cabinet.
#     If it is impossible to support all radios with one cabinet, still propose the single cabinet that supports the maximum number of technologies. In the Reasoning field clearly state either:
#     - which two cabinets would be needed, OR
#     - which specific radio must be stepped-down/removed.
#  7. If shared_cabin = true then after writing the Proposed Cabinet include:
#     "Since Both Operators are Sunset, Flexi Module cabinet can be removed post confirmation from (Operator -1)".
#     If end_of_ee or end_of_3uk contains any date, it is confirmed sunset.
#  Output format — **ONLY valid JSON**, nothing else:
#  {
#    "Proposed Cabinet": "AIRI" | "D-AIRI" | "S-AIRI" | "AIRO" | "D-AIRO" | "S-AIRO" | "Wiltshire" | "Porter" | "Weston" | "Wiltshire + E6130" | "Existing: BTS3900A" | "Existing: BTS3900L" | "None - space constrained" | "Refer to site survey",
#    "Reasoning": "clear step-by-step explanation why this was chosen (follow decision order and explicitly mention how the sketch was analysed for existing BTS3900 and placement)",
#    "StepDown": "No"
#  }
#  Return ONLY the JSON object. No extra text, no markdown, no apologies.
#  Be conservative: if space is marginal or radio compatibility unclear from the sketch → output "Refer to site survey".
# """

# def encode_image(file: UploadFile) -> str:
#     """Encode uploaded file to base64"""
#     content = file.file.read()
#     return base64.b64encode(content).decode("utf-8")

# async def analyse_sketch(
#     target_image: UploadFile = File(..., description="Target site survey photo to check")
# ):
#     try:
        
#         base64_target = encode_image(target_image)

#         # Use provided prompt or default
#         system_content = SYSTEM_PROMPT

#         payload = {
#             "model": VISION_MODEL,
#             "messages": [
#                 {
#                     "role": "system",
#                     "content": system_content
#                 },
#                 {
#                     "role": "user",
#                     "content": [
#                         {"type": "text", "text": "Image 1 (Target) is attached."},
#                         {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_target}"}}
#                     ]
#                 }
#             ],
#             "temperature": 0.2,
#             "max_tokens": 1024,
#             "stream": False
#         }

#         response = requests.post(OLLAMA_URL, json=payload, timeout=1200)

#         if response.status_code != 200:
#             raise HTTPException(status_code=500, detail=f"Ollama error: {response.text}")

#         data = response.json()
#         raw_content = data["choices"][0]["message"]["content"]

#         try:
#             result = extract_json(raw_content)
#         except Exception:
#             result = {"error": "Model did not return valid JSON", "raw": raw_content}

#         return result

#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


import base64
import json
import os
import re
import sys
import logging
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from fastapi import UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from PIL import Image, ImageFile
import io

from call_claude import call_claude

# --- CONFIGURATION ---
REAL_LOGS_ENABLED = True
TERMINAL_LOGS_ENABLED = True

def extract_json(text: str):
    """
    Strips Gemma 4 thinking blocks and extracts the JSON object.
    """
    # Remove <|thought|> ... <|/thought|> if the model outputs them
    clean_text = re.sub(r'<\|thought\|>.*?<\|/thought\|>', '', text, flags=re.DOTALL)
    
    # Find the JSON structure
    match = re.search(r"\{.*\}", clean_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            # Try to fix common trailing commas or minor syntax errors
            fixed = re.sub(r",\s*}", "}", match.group())
            return json.loads(fixed)
    raise ValueError(f"No JSON found in response.")

VLLM_URL = "http://localhost:8000/v1/chat/completions"

# IMPORTANT: This must match the model path or '--served-model-name' used in the startup command
MODEL_NAME = "/home/user/.cache/huggingface/hub/models--google--gemma-4-31B-it/snapshots/439edf5652646a0d1bd8b46bfdc1d3645761a445" 

def get_real_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    if REAL_LOGS_ENABLED:
        log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        log_filename = f"telecom_audit_{datetime.now().strftime('%Y-%m-%d')}.log"
        handler = TimedRotatingFileHandler(os.path.join(log_dir, log_filename), when="midnight", interval=1, backupCount=7)
        handler.setFormatter(log_formatter)
        logger.addHandler(handler)
    return logger

def get_terminal_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    if TERMINAL_LOGS_ENABLED:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter('TERMINAL | %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

logger = get_real_logger(__name__)
t_logger = get_terminal_logger("terminal")


# Your fixed system prompt (very long ? kept as-is)
SYSTEM_PROMPT = """
You are an expert in telecom site infrastructure planning, specialized in Ericsson cabinet families for macro sites (Greenfield, Rooftop, Streetworks / SW).

Your task is to propose **exactly one cabinet solution** (or a named combination when explicitly allowed) that best fits the site constraints and radio requirements.

Input variables you MUST use:

 
The cabin layout sketch / floor-plan drawing is ALWAYS provided as an attached image. You MUST carefully analyse this sketch to:

- Identify if there is an existing BTS3900A / EE 3900A or BTS3900L cabinet.

- Determine exact available space and clearances shown in the drawing.

- All space decisions are now based solely on the sketch (no separate "available space" parameter).

Placement rules based on sketch analysis:

- If the sketch clearly shows a BTS3900A / EE 3900A (or BTS3900L), you MUST remove it and propose the new Ericsson cabinet in its exact location/footprint. Use the dimensions and clearances already marked around that position.

- If there is NO BTS3900A / BTS3900L visible in the sketch, select a new suitable empty location inside the cabin. Prefer placing the new cabinet against a wall (to maintain a proper walkway/aisle in front as per standard telecom practice). Always ensure at least 600 mm extra clearance in depth beyond the cabinet’s own depth for maintenance access and door swing.

- The new cabinet must fit comfortably within the available footprint shown on the sketch. If the fit is marginal, tight, or the sketch is unclear → output "Refer to site survey".

Additional rules:

- If dep_env is Indoor then fencing is always treated as YES even if not given.

- Number of ERS required = 3 x Number of different radio types.

  (Example: radios 4419, 4480 → total ERS = 3 x 2 = 6)

Cabinet families — propose ONLY from this list:

INDOOR / PROTECTED CABINETS / Greenfield & Rooftop

1. AIRI

   - Size(HeightxWidthxDepth): 2000 x 600 x 600 mm

   - Max ERS: 6

   - No PSU (uses DCDU)

   - Radios: 4490, 4480, 4419, 2460, 4486, 2212, 2260, 2262, 8863

   - Fencing required

2. D-AIRI (Double AIRI - side-by-side)

   - Size: 2000 x 1500 x 700 mm

   - Max ERS: 15

   - Radios: same as AIRI

   - Fencing required

3. S-AIRI (Slimline AIRI - used when width < 1500 mm)

   - Size: 2000 x 1200 x 700 mm

   - Max ERS: 15

   - Radios: same as AIRI

   - Fencing required

4. Seperate AIRI

   - Two separate AIRI cabinets placed in different locations (only when space forces it)

   - Size per cabinet: 2000 x 600 x 600 mm

   - Radios: same as AIRI

   - Fencing required

OUTDOOR / EXPOSED CABINETS / Greenfield & Rooftop

5. AIRO

   - Size: 2100 x 750 x 600 mm

   - Max ERS: 3 + BBU + PSU

   - Radios: 4490, 4480, 4419, 2460, 4486, 2212, 2260, 2262 (NO 8863)

   - Fencing required

6. D-AIRO (Double AIRO)

   - Size: 2000 x 1800 x 700 mm

   - Max ERS: 12

   - Radios: same as AIRO

   - Fencing required

7. S-AIRO (Slimline AIRO - when width < 1800 mm)

   - Size: 2000 x 1500 x 700 mm

   - Max ERS: 12

   - Radios: same as AIRO

   - Fencing required

8. Seperate AIRO

   - Two separate AIRO cabinets (only when space forces it)

   - Size per cabinet: 2100 x 750 x 600 mm

   - Radios: same as AIRO (NO 8863)

   - Fencing required

STREETWORKS

9. Wiltshire + E6130

   - (Wiltshire: 1650 x 2000 x 755 mm) + (E6130: 130 x 720 x 760 mm)

   - max 9 ERS

   - radios: 4490, 4480, 4486

   - No fencing required

10. Porter

    - Size: 1452 x 1450 x 650 mm

    - max 6 ERS

    - radios: 4419, 2260, 2262

    - No fencing required

11. Weston

    - Size: 1260 x 770 x 700 mm

    - max 3 ERS

    - radios: 2260

    - No fencing required

12. E6130 standalone

    - Size: 130 x 720 x 760 mm

    - only BBU + PSU (no radios)

    - No fencing required

Decision logic — follow STRICTLY in this order:

**Most Important**: If site_type is Streetworks, use only Streetworks family cabinets (ignore other parameters).

If dep_env is Indoor, always treat fencing as YES.

1. If fencing is NO → MUST use Streetworks family

   - Choose Wiltshire / Porter / Weston / E6130 based on radio types & total ERS.

   - If no radios required (all remote/on-tower) → only E6130.

2. If fencing is YES and site_type is Greenfield/Rooftop → use AIRI-family (if Indoor) or AIRO-family (if Outdoor).

3. For AIRI / AIRO selection:

   - First try single AIRI (Indoor) or single AIRO (Outdoor).

   - If ERS requirement exceeds single cabinet capacity → go to D-AIRI or D-AIRO.

   - If width is too tight on the sketch → go to S-AIRI or S-AIRO.

   - If still impossible with one cabinet → consider Seperate AIRI / Seperate AIRO only if the sketch shows two clearly viable separate locations.

4. Radio compatibility check:

   - The proposed cabinet MUST support all required radios.

5. Space constraints (from sketch only):

   - Cabinet dimensions + minimum 600 mm extra depth clearance must fit in the chosen location (either replacement of BTS3900 or new wall position).

   - Maintain adequate walkway/aisle.

   - Specify the space and give reference of other cabinet for placement of this proposed cabinet

   - If fit is marginal or sketch unclear → output "Refer to site survey".

6. You must propose ONLY ONE cabinet.

   If it is impossible to support all radios with one cabinet, still propose the single cabinet that supports the maximum number of technologies. In the Reasoning field clearly state either:

   - which two cabinets would be needed, OR

   - which specific radio must be stepped-down/removed.

7. If shared_cabin = true then after writing the Proposed Cabinet include:

   "Since Both Operators are Sunset, Flexi Module cabinet can be removed post confirmation from (Operator -1)".

   If end_of_ee or end_of_3uk contains any date, it is confirmed sunset.

Output format — **ONLY valid JSON**, nothing else:

{

  "Proposed Cabinet": "AIRI" | "D-AIRI" | "S-AIRI" | "AIRO" | "D-AIRO" | "S-AIRO" | "Wiltshire" | "Porter" | "Weston" | "Wiltshire + E6130" | "Existing: BTS3900A" | "Existing: BTS3900L" | "None - space constrained" | "Refer to site survey",

  "Reasoning": "clear step-by-step explanation why this was chosen (follow decision order and explicitly mention how the sketch was analysed for existing BTS3900 and placement), also specify the position of proposed cabinet by referring other existing cabinets",

  "StepDown": "No"

}

Return ONLY the JSON object. No extra text, no markdown, no apologies.

Be conservative: if space is marginal or radio compatibility unclear from the sketch → output "Refer to site survey".
 
"""

ImageFile.LOAD_TRUNCATED_IMAGES = True

def encode_image(file_source) -> str:
    """Opens, cleans, and encodes image to base64 to prevent server-side crashes."""
    try:
        if isinstance(file_source, str):
            img = Image.open(file_source)
        else:
            # For FastAPI UploadFile
            img = Image.open(file_source.file)
        
        # Convert to RGB to strip alpha channels or weird palettes that can cause issues
        img = img.convert("RGB")
        
        # Save to a byte buffer as a fresh JPEG
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=95)
        
        # Reset file pointer for FastAPI if needed
        if not isinstance(file_source, str):
            file_source.file.seek(0)
            
        return base64.b64encode(buffered.getvalue()).decode("utf-8")
    except Exception as e:
        logger.error(f"Image preprocessing failed: {e}")
        raise ValueError(f"Could not process image: {e}")

async def analyse_sketch(
    target_image: list[UploadFile] = File(..., description="Target site survey photos"),
    site_type: str = Form(..., description="Existing antenna 1 details"),
                     dep_env: str = Form(..., description="Existing antenna 1 details"),
                     fencing: str = Form(..., description="Existing antenna 1 details"),
                     required_radios: str = Form(..., description="Existing antenna 1 details"),
                     Shared_cabin: str = Form(..., description="Existing antenna 1 details"),
                     end_of_ee: str = Form(..., description="Existing antenna 1 details"),
                     end_of_3uk: str = Form(..., description="Existing antenna 1 details")
):
    try:

        prepared_files = []
        
        # 1. Asynchronously read binary payloads into memory blocks
        for img in target_image:
            img_bytes = await img.read()
            media_type = img.content_type if img.content_type else "image/jpeg"
            
            # Pack file properties as a uniform list tuple: (filename, bytes, media_type)
            prepared_files.append((img.filename, img_bytes, media_type))
            
            # Reset internal stream index to maintain clean multi-read capability
            await img.seek(0)

        f_prompt = f"""
        {SYSTEM_PROMPT}

        Input params:
        site_type: {site_type}
        deployment_environment: {dep_env}
        fencing: {fencing}
        required radios: {required_radios}
        shared_cabin: {Shared_cabin}
        end_of_ee: {end_of_ee}
        end_of_3uk: {end_of_3uk}

        """

        raw_content = await call_claude(
            f_prompt,
            files_data=prepared_files
        )

        
        t_logger.info(f"Audit Result: {raw_content} ")
        return raw_content

    except Exception as e:
        logger.exception("Audit process failed")
        raise HTTPException(status_code=500, detail=str(e))
        