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

REFERENCE_IMAGE_PATH = "ref_img2.png"

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
You are an expert telecom site auditor specializing in identifying front-door cooling equipment on telecom shelters and BTS sites.

You will be given TWO images:
1. Reference Guide – This image shows the exact three possible cooling unit types with clear photos and bullet-point differences for each.
2. Site Photo – This is the real photo of the telecom site you must analyze.

Additional information provided: dep_env = "Indoor"

Follow these steps strictly:

1. First check the value of dep_env.
   • If dep_env = "outdoor", immediately return ONLY this exact sentence and nothing else:
     "No front door cooling equipment present, as it is outdoor site"

2. If dep_env is NOT "outdoor", carefully analyze the Site Photo, focusing ONLY on the front door / cooling unit area.

3. Compare the cooling unit in the Site Photo with the THREE types shown in the Reference Guide. Use both the visual examples AND the exact bullet points written next to each type.

   The three possible types are:
   - 12kW – Pressed Louvre type with security grille(if you see grill like design and it is continuous and no seperation between grill)
   - 16kW – Slotted Louvre type with 3 separate sections(if you see grill like design but divided into 3 sections)
   - 16kW Eco CEMS – Slotted Louvre type (looks similar externally but internal setup different)
   
   If you think it is 16kW, then analyse the other image which shows the inside of cooling equipment, if the inside has green coloured panel or green fans, it is Eco version , if it has white/off-whit coloured panels, it is normal 16kW version.

4. Decide which one matches best. If it does not clearly match any of the three, return "None detected".

5. Output your final answer in this exact JSON format only (no extra text, no explanations outside the JSON):

{
  "cooling_equipment": "12kW – Pressed Louvre type with security grille" OR "16kW – Slotted Louvre type with 3 distinctive separate louvres" OR "16kW Eco CEMS – Slotted Louvre type" OR "None detected",
  "confidence": "high" OR "medium" OR "low",
  "reasoning": "one short sentence explaining the key matching features or why it does not match"
}

Now analyze the images and return only the JSON.
"""

# --- MAIN LOGIC ---
async def analyse_dCoolEquip(
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