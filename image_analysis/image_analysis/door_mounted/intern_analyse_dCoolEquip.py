from fastapi import UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import base64
import requests
import json
from typing import Optional, Dict, Any
import re
import os
import logging
from datetime import date
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
import sys

from model.inference import run_inference
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
from io import BytesIO

REAL_LOGS_ENABLED = True

TERMINAL_LOGS_ENABLED = True
def get_real_logger(name):
    """
    Returns a standard logger that logs to file only if REAL_LOGS_ENABLED is True.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    
    if REAL_LOGS_ENABLED:
        log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_filename = f"telecom_proposal_{date_str}.log"
        log_file_path = os.path.join(log_dir, log_filename)
        rotating_file_handler = TimedRotatingFileHandler(log_file_path, when="midnight", interval=1, backupCount=7, encoding='utf-8')
        rotating_file_handler.setFormatter(log_formatter)
        logger.addHandler(rotating_file_handler)
    
    return logger

def get_terminal_logger(name):
    """
    Returns a logger that logs to the terminal only if TERMINAL_LOGS_ENABLED is True.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    if TERMINAL_LOGS_ENABLED:
        console_handler = logging.StreamHandler(sys.stdout)
        terminal_formatter = logging.Formatter('TERMINAL LOG | req_id: %(req_id)s | payload: %(payload)s | response: %(response)s')
        console_handler.setFormatter(terminal_formatter)
        logger.addHandler(console_handler)
    
    return logger

logger = get_real_logger(__name__)
terminal_logger = get_terminal_logger("terminal_logger")


def extract_json(text: str):
    # remove markdown ```json ``` wrappers if present
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError("No JSON found")

# Your fixed system prompt (very long ? kept as-is)
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

4. Decide which one matches best. If it does not clearly match any of the three, return "None detected".

5. Output your final answer in this exact JSON format only (no extra text, no explanations outside the JSON):

{
  "cooling_equipment": "12kW – Pressed Louvre type with security grille" OR "16kW – Slotted Louvre type with 3 distinctive separate louvres" OR "16kW Eco CEMS – Slotted Louvre type" OR "None detected",
  "confidence": "high" OR "medium" OR "low",
  "reasoning": "one short sentence explaining the key matching features or why it does not match"
}

Now analyze the images and return only the JSON.
"""

REFERENCE_IMAGE_PATH = "ref_img2.png"

async def analyse_dCoolEquip(
    target_image: list[UploadFile] = File(
        ..., 
        description="Target site survey photos (you can send 1 or more)"
    )
):
    try:
        ref_full_path = os.path.join(os.path.dirname(__file__), REFERENCE_IMAGE_PATH)
        ref_image = Image.open(ref_full_path).convert("RGB")

        # Convert uploaded images → PIL
        target_images = []
        for img in target_image:
            contents = await img.read()
            pil_img = Image.open(BytesIO(contents)).convert("RGB")
            target_images.append(pil_img)

        # Combine images (IMPORTANT: reference first)
        all_images = [ref_image] + target_images
        
        raw_output = run_inference(all_images, SYSTEM_PROMPT)
        
        logger.info(f"resp: {raw_output}")

        # Extract JSON
        try:
            result = extract_json(raw_output)
        except Exception as e:
            logger.warning(f"Failed to extract JSON: {e}")
            result = {
                "error": "Model did not return valid JSON",
                "raw": raw_output,
                "identified_model": "Unknown",
                "confidence": "low"
            }

        terminal_logger.info("Analysis completed", extra={
            "req_id": "unknown",
            "payload": f"{len(target_images)} images",
            "response": str(result)
        })

        return result
        
    except Exception as e:
        logger.exception("Error in analyse_dCoolEquip")
        raise HTTPException(status_code=500, detail=str(e))
