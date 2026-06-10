from fastapi import UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import base64
import requests
import json
from typing import Optional, Dict, Any
import re
import os

from PIL import Image
import fitz  # PyMuPDF
from pathlib import Path

from call_gemini import call_llm


def extract_json(text: Any):
    # If it's already a dict, just return it
    if isinstance(text, dict):
        return text
    
    # If it's a string, perform regex search
    if isinstance(text, str):
        # remove markdown ```json 
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    
    raise ValueError(f"No JSON found. Received type: {type(text)}")

CROP_LOGIC = """
# ROLE
You are a Technical Document Analysis Assistant. Your goal is to identify specific architectural diagrams within telecommunications site plans and provide precise cropping coordinates.

# TASK
1. Locate the "Top-View" or "Tower Plan" sketch within the provided image.
2. Ensure the sketch matches the specific height provided in the input (e.g., "18.3m"). Look for the label "TOWER PLAN AT [HEIGHT]" directly beneath the sketch.
3. Calculate the percentage of the image that must be removed (cropped) from the Top, Bottom, Left, and Right edges to isolate only that sketch and its associated markings.
4. Provide the result in a strict JSON format.

# CONSTRAINTS
- The percentages should be expressed as decimals between 0.0 and 1.0 (e.g., 0.15 for 15%).
- Ensure the crop is tight but includes all relevant annotations for that specific plan.
- DO NOT include any conversational text, explanations, or markdown formatting other than the JSON block.

# INPUT DATA
- Target Height: [INSERT_HEIGHT_HERE]

# OUTPUT FORMAT: Strict JSON only, no markdown or text
Example Output:
{
  "top": 0.00,
  "bottom": 0.00,
  "left": 0.00,
  "right": 0.00
}
"""


# Your fixed system prompt (very long ? kept as-is)
SYSTEM_PROMPT = """
Role: You are an expert Telecom Structural and Site Design Engineer. Your specific task is to determine if an existing headframe (Circular, Triangular, or Square) has the capacity to support one additional antenna for every identified sector.
[Core Objectives]
1. Identify Sectors: Use azimuths (e.g., 0°, 120°, 240°) strictly to identify which sector is which. Do not use these numbers to calculate physical space or for any other task.
2. Visual Depth Analysis: Analyze the 2D sketch as a top-down view of a 3D environment. Identify equipment that physically "shadows" or "blocks" the signal path from the rail outward to the horizon.
3. Identify Perimeter Rails: Analyze ONLY the rails/faces where antennas are currently attached. Generally, it would be the outermost rails.
4. Locate Poles: Proposals must be placed on an existing empty pole or a clear location on the perimeter rail where a NEW pole can be installed.
[Naming & Depiction](Mostly names will be with an arrow to the equipment, if no arrow then the closest equipment will be that)
1. Antenna naming: Antennas naming will generally contain letters like HeC1 or EeC1 or complex combination like HeC3/uC1/C3A1 or it will likely contain 'antenna' in the name. It is mostly depicted by a rectangle or curved rectangle with a circle(Pole) at the back.
2. Microwave dish: Name will likely contain 'dish' and its depiction will be like a rectangle with a semi-circle at the back.
3. RRU/MHA: Name will likely contain 'RRU' or 'MHA' and will be depicted by a rectangle generally.
[Technical Constraints & Space Logic]
1. Scaled Footprint Logic: Treat the 2D sketch as a precise, real-life scaled top-down view. Equipment boundaries are defined strictly by the lines in the drawing. If a gap exists between two brackets/yokes on the rail, that gap is physically available and unobstructed.
2. Boresight & Bracket Alignment: Assume antennas do not extend laterally beyond the width of their mounting brackets unless explicitly drawn otherwise. A location is only blocked if another piece of equipment is physically drawn directly in front of the proposed spot's firing path
3. Radial Interference & Clearance: Even if equipment fires in the same direction, they are valid if they are placed far enough apart on the rail so they are not physically in front of one another.
4. The Boresight Blockage Rule: A location is INVALID only if equipment (like a dish on an offset bracket) is physically positioned directly in front of the proposed antenna’s signal path.A location is INVALID if the physical body of a new antenna would overlap with the physical body of an existing antenna, even if the mounting brackets are technically separate.
5. Microwave Pole Restriction: Do NOT mount an antenna on the same pole occupied by a microwave dish. You may mount an antenna on the same rail as a dish, provided they are on different poles.
6. New Pole Proposals: If a rail segment has sufficient linear space and a clear line of sight, you may propose a new antenna even if an empty pole does not currently exist at that spot.
7. Azimuth vs. Physicality: Ignore numerical azimuth for space checks. Focus on whether equipment is "in front" of the proposed location.
[Decision Logic]
1. Map Equipment Footprints: Do not just look for "empty rail." Look at the 2D width of the antenna. If placing a new antenna causes its "box" to collide with or sit behind an existing "box," it is a failure.
2. Analyze Rail Gaps: Identify segments of the perimeter rail with sufficient width for a new antenna.
3. Feasibility Check: Mark a sector as "Extra Space" if there is a rail gap that is physically wide enough AND the signal path isn't directly blocked by offset equipment.
4. Geometric Precision: Map footprints based strictly on the provided drawing. Do not assume "extra width" for antennas or "shadowing" from adjacent rails if the drawing shows a clear path. If there is a visible gap on the perimeter rail between two yokes, it is considered sufficient for a new proposal regardless of corner proximity, provided the boxes do not touch.
[Required Output Format]
Sector Proposal & Space Analysis
1. Sector Identification:
- Total Sectors Found: [Number]
- Orientations: [List degrees]
2. Sector-by-Sector Space Assessment:
Sector [Degree]:
- Current Occupancy: [e.g., 1 Antenna, 1 Dish at the end of the rail]
- Proposal Status: [Valid / Invalid]
- Reason: [Explain the physical layout; e.g., "There is a significant gap between the existing antenna and dish where a new pole can be proposed without signal interference."]
- Available Proposal Locations: [Describe the empty pole or the specific rail gap for a new pole proposal]
3. Final Feasibility Summary:
- Conclusion: [Extra Space Confirmed / Partial Space / No Space]
- Visual Justification: Reference physical layout (e.g., "Sector 60 has enough rail space in the middle for a new antenna proposal between the existing equipment").
"""

def get_pdf_page_as_image(pdf_path: str, page_number: int) -> str:
    """
    Opens a local PDF, crops the right-side title block, 
    renders to PNG, and returns the image path.
    """
    try:
        doc = fitz.open(pdf_path)
        
        if page_number < 1 or page_number > len(doc):
            doc.close()
            raise ValueError(f"Page {page_number} is out of range.")

        page = doc.load_page(page_number - 1)
        
        # --- CROP LOGIC START ---
        # Get original page dimensions
        rect = page.rect  # Rect(x0, y0, x1, y1)
        
        # Define the width to keep (e.g., 82% of the width)
        # Based on your sample, the sidebar is roughly 18-20% of the page.
        keep_percentage = 0.865
        new_width = rect.width * keep_percentage
        
        # Create a clipping rectangle: (left, top, right, bottom)
        # We keep full height but limit the right boundary
        clip_rect = fitz.Rect(0, 0, new_width, rect.height)
        # --- CROP LOGIC END ---

        # Set resolution (Matrix(2, 2) = 144 DPI)
        matrix = fitz.Matrix(2, 2)
        
        # Pass the 'clip' parameter to get_pixmap
        pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, clip=clip_rect)
        
        image_path = f"temp_analysis_page_{page_number}.png"
        pix.save(image_path)
        
        doc.close()
        return image_path

    except Exception as e:
        raise Exception(f"Failed to process and crop PDF: {str(e)}")
    
    
def crop_image(image_path: str, top_pct: float, bottom_pct: float, left_pct: float, right_pct: float) -> str:
    """
    Crops an image based on percentages to remove from each side.
    Percentages should be floats (e.g., 0.10 for 10%).
    """
    try:
        with Image.open(image_path) as img:
            width, height = img.size

            # Calculate pixel coordinates for cropping
            # left, top, right, bottom
            left = width * left_pct
            top = height * top_pct
            right = width * (1 - right_pct)
            bottom = height * (1 - bottom_pct)

            # Perform crop
            img_cropped = img.crop((left, top, right, bottom))
            
            # Overwrite the temp image or save as new
            cropped_path = f"cropped_{image_path}"
            img_cropped.save(cropped_path)
            
            return cropped_path
    except Exception as e:
        raise Exception(f"Failed to crop image: {str(e)}")

async def analyse_struc_space(
    page_number: int,
    target_height: float,
    pdf_file: str = Form(None, description="The technical drawing PDF")
):
    temp_image = None
    
    # Simple check to see if the path provided even exists
    if not os.path.exists(pdf_file):
        raise HTTPException(status_code=404, detail=f"File not found at: {pdf_file}")

    try:
        # 1. Convert the specific page to an image
        raw_image = get_pdf_page_as_image(pdf_file, page_number)
        
        formatted_crop_prompt = f"""
        
        {CROP_LOGIC}
        
        # INPUT DATA
        - Target Height: {target_height}m
        
        """
        
        crop_response = await call_llm(formatted_crop_prompt, image_paths=[raw_image])
        
        if isinstance(crop_response, dict) and "candidates" in crop_response:
    # Navigate to the text part of the first candidate
            raw_text = crop_response['candidates'][0]['content']['parts'][0]['text']
        else:
            # If it's already a string or a different format
            raw_text = crop_response
        
        # 4. Parse the JSON from the LLM response
        coords = extract_json(raw_text)
        
        # Validate coordinates exist (safety check)
        required_keys = ["top", "bottom", "left", "right"]
        if not all(k in coords for k in required_keys):
            raise ValueError(f"LLM returned incomplete coordinates: {coords}")

        # 5. Apply the crop using the automated values
        cropped_image = crop_image(
            raw_image, 
            float(coords["top"]), 
            float(coords["bottom"]), 
            float(coords["left"]), 
            float(coords["right"])
        )
        
        # 2. Send the image to your call_llm function
        # Ensure call_llm is imported and configured correctly
        # gemini_response = await call_llm(SYSTEM_PROMPT, image_paths=[temp_image])

        # return gemini_response
        
        return {
            "cropped_image_path": cropped_image,
            "crop_coordinates": coords}
    

    except Exception as e:
        print(f"Structural Analysis Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        # 3. Always clean up the temporary image to save disk space
        if temp_image and os.path.exists(temp_image):
            os.remove(temp_image)
            
            
            


"""
Role: You are an expert Telecom Structural and Site Design Engineer. Your specific task is to determine if an existing headframe (Circular, Triangular, or Square) has the capacity to support one additional antenna for every identified sector.
[Core Objectives]
1. Identify sketch: Analyze the provided image, it can contain multiple sketches and unnecessary details. Focus only on the top-view sketch of the headframe which is at the input_height level. Ignore any side views, elevation drawings, or details that do not pertain to the top-down layout of the headframe.
2. Identify Sectors: Use azimuths (e.g., 0°, 120°, 240°) strictly to identify which sector is which. Do not use these numbers to calculate physical space or for any other task.
3. Visual Depth Analysis: Analyze the 2D sketch as a top-down view of a 3D environment. Identify equipment that physically "shadows" or "blocks" the signal path from the rail outward to the horizon.
4. Identify Perimeter Rails: Analyze ONLY the rails/faces where antennas are currently attached. Generally, it would be the outermost rails.
5. Locate Poles: Proposals must be placed on an existing empty pole or a clear location on the perimeter rail where a NEW pole can be installed.
[Naming & Depiction](Mostly names will be with an arrow to the equipment, if no arrow then the closest equipment will be that)
1. Antenna naming: Antennas naming will generally contain letters like HeC1 or EeC1 or complex combination like HeC3/uC1/C3A1 or it will likely contain 'antenna' in the name. It is mostly depicted by a rectangle or curved rectangle with a circle(Pole) at the back.
2. Microwave dish: Name will likely contain 'dish' and its depiction will be like a rectangle with a semi-circle at the back.
3. RRU/MHA: Name will likely contain 'RRU' or 'MHA' and will be depicted by a rectangle generally.
[Technical Constraints & Space Logic]
1. Scaled Footprint Logic: Treat the 2D sketch as a precise, real-life scaled top-down view. If the sketch shows a gap between two pieces of equipment, that gap is real and can be used for proposals. If the sketch shows equipment touching or overlapping, they are physically blocking each other regardless of how close they are to the center or corner.
2. Boresight: Assume antennas do not extend laterally beyond the width as shown unless explicitly drawn. A location is only blocked if another piece of equipment is physically drawn directly in front of the proposed spot's firing path
3. Radial Interference & Clearance: Even if equipment fires in the same direction, they are valid if they are placed far enough apart on the rail so they are not physically in front of one another.
4. The Boresight Blockage Rule: A location is INVALID if equipment (like a dish on an offset bracket) is physically positioned directly in front of the proposed antenna's signal path.A location is INVALID if the physical body of a new antenna would overlap with the physical body of an existing antenna, even if the mounting brackets are technically separate.
5. Microwave Pole Restriction: Do NOT mount an antenna on the same pole occupied by a microwave dish. You may mount an antenna on the same rail as a dish, provided they are on different poles.
6. New Pole Proposals: If a rail segment has sufficient linear space and a clear line of sight, you may propose a new antenna even if an empty pole does not currently exist at that spot.
7. Azimuth vs. Physicality: Ignore numerical azimuth for space checks. Focus on whether equipment is "in front" of the proposed location.
[Decision Logic]
1. Map Equipment Footprints: Do not just look for "empty rail." Look at the 2D width of the antenna. If placing a new antenna causes its "box" to collide with or sit behind an existing "box," it is a failure.
2. Analyze Rail Gaps: Identify segments of the perimeter rail with sufficient width for a new antenna.
3. Feasibility Check: Mark a sector as "Extra Space" if there is a rail gap that is physically wide enough AND the signal path isn't directly blocked by offset equipment. Analyse the physical space required by analysing existing antenna footprints and the gaps between them. If a new antenna can fit in a gap without overlapping an existing antenna's footprint, it is a valid proposal.
4. Geometric Precision: Map footprints based strictly on the provided drawing. Do not assume "extra width" for antennas or "shadowing" from adjacent rails if the drawing shows a clear path. If there is a visible gap on the perimeter rail between two yokes, it is considered sufficient for a new proposal regardless of corner proximity, provided the boxes do not touch.
[Required Output Format]
Sector Proposal & Space Analysis
1. Sector Identification:
- Total Sectors Found: [Number]
- Orientations: [List degrees]
2. Sector-by-Sector Space Assessment:
Sector [Degree]:
- Current Occupancy: [e.g., 1 Antenna, 1 Dish at the end of the rail]
- Proposal Status: [Valid / Invalid]
- Reason: [Explain the physical layout; e.g., "There is a significant gap between the existing antenna and dish where a new pole can be proposed without signal interference."]
- Available Proposal Locations: [Describe the empty pole or the specific rail gap for a new pole proposal]
3. Final Feasibility Summary:
- Conclusion: [Extra Space Confirmed / Partial Space / No Space]
- Visual Justification: Reference physical layout (e.g., "Sector 60 has enough rail space in the middle for a new antenna proposal between the existing equipment").
"""