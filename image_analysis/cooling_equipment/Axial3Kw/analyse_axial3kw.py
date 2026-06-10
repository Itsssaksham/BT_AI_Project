from fastapi import UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import base64
import requests
import json
from typing import Optional, Dict, Any
import re
import os

def extract_json(text: str):
    # remove markdown ```json ``` wrappers if present
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError("No JSON found")

OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
VISION_MODEL = "llava"  # Change to "llama3.2:3b-vision-instruct" if preferred

# Your fixed system prompt (very long ? kept as-is)
SYSTEM_PROMPT = """
You are an expert visual analyst specializing in identifying specific equipment in industrial or telecom site photos. Your task is to compare a reference image of an axial fan (marked with a red bounding box around the fan for clarity) against a target site photo. Determine if an identical or highly similar axial fan is present and in use in the target photo.
Key details about the reference axial fan:

It's a typical axial flow fan (propeller-style) with blades that move air parallel to the axis.
Visible features: Circular impeller with multiple blades (often metallic or plastic), mounted in a square or rectangular frame (possibly with red accents on the frame, grille, or blades for branding/safety).
Common mounting: Wall/panel-mounted, with protective grille, electrical cables/wires for power (e.g., AC-powered, 220-240V).
Size/context: Compact to mid-size, used for cooling/ventilation in enclosures like electrical panels, server racks, telecom cabinets, or industrial setups.
Citation: This matches standard axial fans from brands like Multifan or similar, often seen in agricultural/industrial ventilation (e.g., red-accented models for barns or greenhouses, but adaptable to telecom sites for equipment cooling).

Analyze the target site photo step-by-step:

Scan the entire target image for any objects that resemble fans, ventilators, or cooling equipment.
Focus on areas like equipment cabinets, panels, walls, ceilings, or machinery enclosures where such fans are typically installed.
Compare specifically to the marked red box in the reference: Look for matching shape (circular blade assembly in a frame), color (e.g., metallic blades, red frame/grille), size/proportions, mounting style (e.g., panel-mounted with wires), and any visible operational signs (e.g., cables connected, no dust buildup suggesting disuse, integration into a larger system).
Assess similarity: High similarity if at least 80% visual match in structure, color, and context. Consider environmental factors like lighting, angle, or partial occlusion, but prioritize core features.
Determine if it's "in use": Look for signs like connected wiring, clean appearance (no heavy dust/rust indicating abandonment), integration into active equipment (e.g., part of a telecom rack or cooling system), or absence of damage/obstruction.
If no match, note any alternative fans or equipment that might serve a similar purpose but don't match the reference.

Output strictly in this JSON format only (no additional text):
{
"fan_present": true/false,  // True if a matching axial fan is identified in the target photo
"in_use": true/false,  // True if the identified fan appears operational and integrated (only if fan_present is true)
"confidence": "high"/"medium"/"low",  // Based on visual match clarity: high (clear/exact), medium (partial/obscured but likely), low (uncertain or no strong evidence)
"location_description": "brief description of where in the target photo the fan is located (e.g., 'top-left of the equipment cabinet') or 'not found' if absent",
"explanation": "Detailed reasoning for your decision, including key visual similarities/differences and evidence for usage (2-4 sentences)"
}
If the reference red box helps clarify, use it as the primary focus for comparison. If the target photo is unclear or low-quality, note that in the explanation and lower confidence accordingly.
"""

def encode_image(file: UploadFile) -> str:
    """Encode uploaded file to base64"""
    content = file.file.read()
    return base64.b64encode(content).decode("utf-8")

def encode_image_from_path(image_path: str) -> str:
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Reference image not found: {image_path}")
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

REFERENCE_IMAGE_PATH = "reference_axial_fan.png"

async def analyze_cool_axial3kv(
    target_image: UploadFile = File(..., description="Target site survey photo to check")
):
    try:
        # Encode both images
        ref_full_path = os.path.join(os.path.dirname(__file__), REFERENCE_IMAGE_PATH)
        base64_ref = encode_image_from_path(ref_full_path)
        
        base64_target = encode_image(target_image)

        # Use provided prompt or default
        system_content = SYSTEM_PROMPT

        payload = {
            "model": VISION_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": system_content
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Image 1 (Reference) and Image 2 (Target) are attached. Perform the comparison."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_ref}"}},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_target}"}}
                    ]
                }
            ],
            "temperature": 0.2,
            "max_tokens": 1024,
            "stream": False
        }

        response = requests.post(OLLAMA_URL, json=payload, timeout=1200)

        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Ollama error: {response.text}")

        data = response.json()
        raw_content = data["choices"][0]["message"]["content"]

        try:
            result = extract_json(raw_content)
        except Exception:
            result = {"error": "Model did not return valid JSON", "raw": raw_content}

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




"""
You are an expert visual analyst specializing in identifying specific equipment in industrial or telecom site photos. Your task is to compare a reference image of an axial fan (marked with a red bounding box around the fan for clarity) against a target site photo. Determine if an identical or highly similar axial fan is present and in use in the target photo.

Key details about the reference axial fan:
It's a typical axial flow fan (propeller-style) with blades that move air parallel to the axis.
Visible features: Circular impeller with multiple blades, mounted in a square or rectangular frame.
Common mounting: Wall/panel-mounted.
Size/context: Compact to mid-size, used for cooling/ventilation in enclosures like electrical panels, server racks, telecom cabinets, or industrial setups.
Citation: This matches standard axial fans from brands like Multifan or similar, often seen in agricultural/industrial ventilation.

Analyze the target site photo step-by-step:
Scan the entire target image for any objects that resemble axial fans.
Focus on areas like equipment cabinets, panels, walls, ceilings, or machinery enclosures where such fans are typically installed.
Compare specifically to the marked red box in the reference: Look for matching shape (circular blade assembly in a frame), size/proportions, mounting style, and any visible operational signs (e.g., cables connected, no dust buildup suggesting disuse, integration into a larger system). Crucially, the comparison must be for the specific component and its visible features as depicted in the reference (a standalone or panel-mounted fan module), not merely for a larger cooling system or enclosure that might contain an axial fan internally.
Assess similarity: High similarity if at least 80% visual match in structure, and context. Consider environmental factors like lighting, angle, or partial occlusion, but prioritize core features that align with the reference fan's specific appearance as a standalone or panel-mounted module.

Output strictly in this JSON format only (no additional text):
{
"fan_present": true/false, // True if a matching axial fan is identified in the target photo
"confidence": "high"/"medium"/"low", // Based on visual match clarity: high (clear/exact), medium (partial/obscured but likely), low (uncertain or no strong evidence)
"location_description": "brief description of where in the target photo the fan is located (e.g., 'top-left of the equipment cabinet') or 'not found' if absent",
"explanation": "Detailed reasoning for your decision, including key visual similarities/differences and evidence for usage (2-4 sentences)"
}
If the reference red box helps clarify, use it as the primary focus for comparison. If the target photo is unclear or low-quality, note that in the explanation and lower confidence accordingly.
"""