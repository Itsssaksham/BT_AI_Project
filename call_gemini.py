import httpx
import base64
import json
import os
import requests
import time

async def wait_for_file_active(file_name, api_key):
    """
    Polls the Gemini File API until the file state is 'ACTIVE'.
    """
    get_url = f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={api_key}"
    
    while True:
        async with httpx.AsyncClient() as client:
            response = await client.get(get_url)
            file_info = response.json()
            state = file_info.get("state")

            if state == "ACTIVE":
                print("File is ready.")
                return True
            elif state == "FAILED":
                raise Exception("File processing failed.")
            
            print(f"File state is {state}. Waiting 5 seconds...")
            time.sleep(5) # Use asyncio.sleep(5) if in an async loop

async def upload_file_to_gemini(file_path, api_key):

    upload_url = (
        "https://generativelanguage.googleapis.com/upload/v1beta/files"
        f"?key={api_key}"
    )

    file_size = os.path.getsize(file_path)

    ext = file_path.lower()

    if ext.endswith(".mp4"):
        mime_type = "video/mp4"

    elif ext.endswith(".png"):
        mime_type = "image/png"

    elif ext.endswith((".jpg", ".jpeg")):
        mime_type = "image/jpeg"

    else:
        raise Exception(f"Unsupported file format: {file_path}")

    # -------------------------------------------------
    # START RESUMABLE UPLOAD
    # -------------------------------------------------

    start_headers = {
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(file_size),
        "X-Goog-Upload-Header-Content-Type": mime_type,
        "Content-Type": "application/json"
    }

    metadata = {
        "file": {
            "display_name": os.path.basename(file_path)
        }
    }

    start_response = requests.post(
        upload_url,
        headers=start_headers,
        json=metadata
    )

    if start_response.status_code != 200:
        raise Exception(
            f"Gemini upload start failed: "
            f"{start_response.text}"
        )

    upload_session_url = start_response.headers.get(
        "X-Goog-Upload-URL"
    )

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    upload_headers = {
        "X-Goog-Upload-Command": "upload, finalize",
        "X-Goog-Upload-Offset": "0",
        "Content-Length": str(len(file_bytes))
    }

    upload_response = requests.post(
        upload_session_url,
        headers=upload_headers,
        data=file_bytes
    )

    if upload_response.status_code != 200:
        raise Exception(
            f"Gemini upload failed: "
            f"{upload_response.text}"
        )

    response_json = upload_response.json()

    file_info = response_json["file"]

    return {
        "file_name": file_info["name"],
        "file_uri": file_info["uri"],
        "mime_type": file_info["mimeType"]
    }


# =========================================================
# DELETE GEMINI FILE
# =========================================================

async def delete_gemini_file(file_name, api_key):

    delete_url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"{file_name}?key={api_key}"
    )

    response = requests.delete(delete_url)

    if response.status_code != 200:
        print(f"Gemini delete failed: {response.text}")


async def call_llm(Prompt, image_paths=None):

    """
    Existing image flow still works.

    New:
    - mp4 files automatically use Gemini Files API
    """

    
    gemini_api_key = ""

    gemini_direct_url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-3.5-flash:generateContent"
        f"?key={gemini_api_key}"
    )

    parts = [
        {
            "text": Prompt
        }
    ]

    uploaded_files_to_delete = []

    try:

        # =====================================================
        # HANDLE MEDIA
        # =====================================================

        if image_paths:

            for media_path in image_paths:

                ext = media_path.lower()

                # =================================================
                # VIDEO FLOW -> FILES API
                # =================================================

                if ext.endswith(".mp4"):

                    uploaded_file = await upload_file_to_gemini(
                        media_path,
                        gemini_api_key
                    )
                    
                    

                    uploaded_files_to_delete.append(
                        uploaded_file["file_name"]
                    )
                    
                    await wait_for_file_active(uploaded_file["file_name"], gemini_api_key)

                    parts.append(
                        {
                            "fileData": {
                                "mimeType": uploaded_file["mime_type"],
                                "fileUri": uploaded_file["file_uri"]
                            }
                        }
                    )

                # =================================================
                # IMAGE FLOW -> INLINE DATA (OLD FLOW)
                # =================================================

                else:

                    try:

                        with open(media_path, "rb") as image_file:

                            encoded_image = base64.b64encode(
                                image_file.read()
                            ).decode("utf-8")

                        # MIME TYPES

                        if ext.endswith(".png"):
                            mime_type = "image/png"

                        elif ext.endswith((".jpg", ".jpeg")):
                            mime_type = "image/jpeg"

                        elif ext.endswith(".webp"):
                            mime_type = "image/webp"

                        elif ext.endswith((".heic", ".heif")):
                            mime_type = "image/heic"

                        elif ext.endswith(".pdf"):
                            mime_type = "application/pdf"

                        else:
                            print(
                                f"Unsupported format: {media_path}"
                            )
                            continue

                        parts.append(
                            {
                                "inlineData": {
                                    "mimeType": mime_type,
                                    "data": encoded_image
                                }
                            }
                        )

                    except Exception as e:

                        print(
                            f"Error processing image "
                            f"{media_path}: {e}"
                        )

        # =====================================================
        # GEMINI REQUEST
        # =====================================================

        direct_api_payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": parts
                }
            ],
            "generationConfig": {
                "temperature": 0.8,
                "topP": 0.9,
                "maxOutputTokens": 65536
            },
            "safetySettings": [
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_NONE"
                }
            ]
        }

        async with httpx.AsyncClient(
            timeout=300.0
        ) as client:

            gemini_response = await client.post(
                gemini_direct_url,
                json=direct_api_payload,
                headers={
                    "Content-Type": "application/json"
                }
            )

        if gemini_response.status_code != 200:

            raise Exception(
                f"Gemini API error: "
                f"{gemini_response.status_code} - "
                f"{gemini_response.text}"
            )

        return gemini_response.json()

    finally:

        # =====================================================
        # AUTO DELETE GEMINI FILES
        # =====================================================

        for file_name in uploaded_files_to_delete:

            try:

                await delete_gemini_file(
                    file_name,
                    gemini_api_key
                )

            except Exception as e:

                print(
                    f"Gemini delete failed "
                    f"for {file_name}: {e}"
                )


# async def call_llm(Prompt, image_paths=None):
#     """
#     Calling LLM with text and optional multiple images.
#     image_paths should be a list of file paths to your images.
#     """
#  # Free key: AIzaSyCtDTVY-51eLFblC0P_zN3Ja5sg6oJ8FQM
#  # Paid key: AIzaSyDI7MyjFQqYl54ptAueOdDDQtEITWaC4o0
 
    
#     gemini_api_key = "AIzaSyDI7MyjFQqYl54ptAueOdDDQtEITWaC4o0"
#     gemini_direct_url = (
#         "https://generativelanguage.googleapis.com/v1beta/"
#         "models/gemini-3-flash-preview:generateContent"
#         f"?key={gemini_api_key}"
#     )

#     parts = [
#         {
#             "text": Prompt
#         }
#     ]

#     if image_paths:
#         for image_path in image_paths:
#             try:
#                 with open(image_path, "rb") as image_file:
#                     encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
                
#                 # Get lowercased path for extension check (fix for 'ext' not defined)
#                 ext = image_path.lower()
                
#                 # Determine MIME type based on file extension
#                 if ext.endswith('.png'):
#                     mime_type = "image/png"
#                 elif ext.endswith(('.jpg', '.jpeg')):
#                     mime_type = "image/jpeg"
#                 elif ext.endswith('.webp'):
#                     mime_type = "image/webp"
#                 elif ext.endswith(('.heic', '.heif')):
#                     mime_type = "image/heic"  # Or image/heif
#                 elif ext.endswith('.pdf'):
#                     mime_type = "application/pdf"
#                 else:
#                     print(f"Warning: Unsupported image format for {image_path}. Skipping.")
#                     continue

#                 parts.append(
#                     {
#                         "inlineData": {
#                             "mimeType": mime_type,
#                             "data": encoded_image
#                         }
#                     }
#                 )
#             except FileNotFoundError:
#                 print(f"Error: Image file not found at {image_path}. Skipping.")
#                 continue
#             except Exception as e:
#                 print(f"Error processing image {image_path}: {e}. Skipping.")
#                 continue

#     direct_api_payload = {
#         "contents": [
#             {
#                 "role": "user",
#                 "parts": parts
#             }
#         ],
#         "generationConfig": {
#             "temperature": 0.1,
#             "topP": 0.9,
#             "maxOutputTokens": 65536
#         },
#         "safetySettings": [
#             {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
#             {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
#             {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
#             {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
#         ]
#     }

#     async with httpx.AsyncClient(timeout=180.0) as client:
#         gemini_response = await client.post(
#             gemini_direct_url,
#             json=direct_api_payload,
#             headers={"Content-Type": "application/json"}
#         )

#     if gemini_response.status_code != 200:
#         # You would typically raise HTTPException here, similar to your original code
#         raise Exception(f"Gemini API error: {gemini_response.status_code} - {gemini_response.text}")

#     gemini_json = gemini_response.json()
    
#     return gemini_json