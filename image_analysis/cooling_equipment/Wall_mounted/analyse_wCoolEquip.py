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

# --- CONFIGURATION ---
REAL_LOGS_ENABLED = True
TERMINAL_LOGS_ENABLED = True

# vLLM default endpoint
VLLM_URL = "http://localhost:8000/v1/chat/completions"

# IMPORTANT: This must match the model path or '--served-model-name' used in the startup command
MODEL_NAME = "/home/user/.cache/huggingface/hub/models--google--gemma-4-31B-it/snapshots/439edf5652646a0d1bd8b46bfdc1d3645761a445" 

REFERENCE_IMAGE_PATH = "lref_img2.png"

# --- LOGGER SETUP ---
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

# --- UTILS ---
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


# Allow Pillow to handle slightly broken files locally
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

# --- PROMPT ---
SYSTEM_PROMPT = """
Analyze the provided images of telecom site cooling units. You are provided with 1 reference image(you have to analyse all the cooling equipment provided in this image and you can match it with the target photo with which it looks similar) and target photo(you have to analyse this image and tell which cooling equipment is this). General Conditions for Identification: * Connectivity: A cooling unit is only considered 'in use' and should be identified if it is visibly connected with electrical wires. If a fan unit matches a description but lacks clear wire connections, it is 'not in use' and should not be included in the output. * Counting for Dual Units: For 'Dual' units, ensure two distinct fans of the specified type are present within the same cooling setup or immediate proximity. Fan Type Visual Characteristics and Power Ratings: 1. Centrifugal Fan (5kW): * Appearance: These fans will typically appear cylindrical or barrel-shaped, often blue as seen in the example images (previously provided). They have a prominent front gridded intake (like a circular cage) and a side or rear discharge. * Airflow Principle: Air is drawn in axially (from the front) and expelled centrifugally (at a right angle to the intake, though the ducting might redirect it). * Mounting: Often mounted horizontally to channels or walls. 2. Dual Centrifugal Fan (10kW): * Appearance: Two fans matching the description of a 'Centrifugal Fan' positioned together, often in parallel, within the same cooling enclosure or immediately adjacent. 3. AC Fan (8kW): * Appearance: These fans are typically flat, square-housed units designed for wall or panel mounting. They feature a prominent circular metal grill on the front, protecting visible blades behind it. The blades are often black or dark grey. There's usually a central hub covering the motor. The overall unit sits flush or slightly recessed into a wall/panel. * Mounting: Integrated directly into a wall, panel, or cabinet opening with a square frame. * Connectivity: Look for electrical wiring, often connected to a nearby switch or junction box, confirming it's active. 4. Dual AC Fan (14kW): * Appearance: Two fans matching the description of an 'AC Fan' positioned together, often side-by-side or stacked, within the same cooling enclosure or immediate vicinity. 5. DC Fan (5kW): * Appearance: These fans are typically rectangular or square modules, often with a white or metallic (galvanized steel) casing, designed for integration into a cabinet or ceiling panel. They feature a visible circular fan with a protective grill, often recessed into the unit's body. There might be a brand name on the housing (e.g., "DUNHAM-BUSH"). They often have a compact appearance compared to AC fans, and the wiring may appear less robust than high-power AC units, sometimes connecting to smaller terminals or control boards. Look for a red/yellow power switch if present. * Mounting: Often mounted into the ceiling or upper wall of a cabinet/room, or integrated within larger cooling units. * Connectivity: Pay close attention to visible wiring, which might be less heavy-duty than for AC units, often connecting to control modules or smaller junction points. 6. Dual DC Fan (10kW): * Appearance: Two fans matching the description of a 'DC Fan' positioned together, often side-by-side or within a shared, larger rectangular housing, within the same cooling enclosure or immediate vicinity 7. Axial Fan (3kW): * Appearance: These fans are typically compact, often found within a larger piece of equipment or mounted directly to a panel. They feature prominent, often metallic (silver/grey) blades that rotate around a central hub, designed to move air straight through. The blades are generally wide and flat. The image shows a small, directly exposed fan. * Airflow Principle: Airflow is parallel to the fan's axis of rotation, moving directly from front to back. * Mounting: Often integrated within other components or as standalone small cooling units, sometimes with minimal housing beyond the blades and central motor. * Connectivity: Look for small gauge wiring connecting directly to the motor or a nearby terminal, confirming it's active. Output Format: [Fan Type] ([Power Rating]) [Small reason for your selection]"
"""

# --- MAIN LOGIC ---
async def analyse_wCoolEquip(
    target_image: List[UploadFile] = File(..., description="Target site survey photos")
):
    try:
        # 1. Encode Images
        ref_path = os.path.join(os.path.dirname(__file__), REFERENCE_IMAGE_PATH)
        b64_ref = encode_image(ref_path)
        
        # 2. Construct Multi-modal Content
        # vLLM/OpenAI format requires interleaving text and image objects
        user_content = [
            {"type": "text", "text": "Image 1 is the Reference. The following are Site Photos. Identify the model."}
        ]
        
        # Add Reference
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64_ref}"}
        })
        
        # Add Targets
        for img in target_image:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encode_image(img)}"}
            })

        # 3. Construct Payload
        payload = {
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.1,
            "max_tokens": 1024,
            "stream": False
        }

        t_logger.info(f"Dispatching request to vLLM (Gemma 4 31B BF16) with {len(target_image)} site photos.")
        
        # 4. Request
        response = requests.post(VLLM_URL, json=payload, timeout=600)
        
        if response.status_code != 200:
            logger.error(f"vLLM Error: {response.text}")
            raise HTTPException(status_code=500, detail=f"Inference Engine Error: {response.status_code}")

        # 5. Process Output
        data = response.json()
        raw_content = data["choices"][0]["message"]["content"]
        
        # Handle the "outdoor" string return vs JSON return
        if "outdoor site" in raw_content.lower():
            return {"message": raw_content}

        try:
            result = extract_json(raw_content)
        except Exception as e:
            logger.warning(f"Parse error: {e}")
            result = {
                "error": "JSON parsing failed",
                "raw_text": raw_content
            }

        t_logger.info(f"Audit Result: {result.get('cooling_equipment', 'None Detected')}")
        return result

    except Exception as e:
        logger.exception("Audit process failed")
        raise HTTPException(status_code=500, detail=str(e))