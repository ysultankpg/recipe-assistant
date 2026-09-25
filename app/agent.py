# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import json
import os
import re
import urllib.parse
import urllib.request

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore, storage
from google.genai import types

from .a2ui_utils import a2ui_callback

# IMPORTANT: Hardcode project ID string for Firestore client & GCS bucket
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-02-d6cd529c0ad9"
GCS_BUCKET_NAME = "recipe-assistant-assets-qwiklabs-gcp-02-d6cd529c0ad9"
MEMORY_BANK_ID = "3999314666604986368"

# Load Agent Engine resource name from deployment_metadata.json
DEPLOYMENT_METADATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "deployment_metadata.json"
)
AGENT_ENGINE_RESOURCE_NAME = f"projects/{FIRESTORE_PROJECT_ID}/locations/us-central1/reasoningEngines/{MEMORY_BANK_ID}"

if os.path.exists(DEPLOYMENT_METADATA_PATH):
    try:
        with open(DEPLOYMENT_METADATA_PATH, "r") as f:
            metadata = json.load(f)
            AGENT_ENGINE_RESOURCE_NAME = metadata.get(
                "remote_agent_runtime_id", AGENT_ENGINE_RESOURCE_NAME
            )
            MEMORY_BANK_ID = AGENT_ENGINE_RESOURCE_NAME.split("/")[-1]
    except Exception:
        pass


async def generate_memories_callback(callback_context: CallbackContext):
    """WRITE: After each turn, send the session events to Memory Bank for fact extraction."""
    try:
        await callback_context.add_session_to_memory()
    except (ValueError, AttributeError, Exception):
        # Ignore when running in test contexts where no memory service is attached
        pass
    return None


def memory_bank_service_builder():
    """Builds VertexAiMemoryBankService for deployed container runtime."""
    return VertexAiMemoryBankService(
        project=FIRESTORE_PROJECT_ID,
        location="us-central1",
        agent_engine_id=MEMORY_BANK_ID,
    )


def search_recipes(query: str = "", cuisine: str = "") -> str:
    """Searches the Firestore recipe collection by keyword or cuisine filter.

    Args:
        query: Optional search term to match in recipe title, ingredients, or tags.
        cuisine: Optional cuisine filter (e.g. Italian, Mexican, Asian, Mediterranean).

    Returns:
        A JSON string containing a list of matching recipe summaries.
    """
    db = firestore.Client(project=FIRESTORE_PROJECT_ID)
    docs = db.collection("recipes").stream()

    results = []
    query_lower = query.lower() if query else ""
    cuisine_lower = cuisine.lower() if cuisine else ""

    for doc in docs:
        data = doc.to_dict()
        title = data.get("title", "").lower()
        rec_cuisine = data.get("cuisine", "").lower()
        ingredients = [i.lower() for i in data.get("ingredients", [])]
        tags = [t.lower() for t in data.get("dietary_tags", [])]

        matches_cuisine = not cuisine_lower or cuisine_lower in rec_cuisine
        matches_query = not query_lower or (
            query_lower in title or
            any(query_lower in ing for ing in ingredients) or
            any(query_lower in tag for tag in tags)
        )

        if matches_cuisine and matches_query:
            results.append({
                "recipe_id": data.get("recipe_id"),
                "title": data.get("title"),
                "cuisine": data.get("cuisine"),
                "prep_time_minutes": data.get("prep_time_minutes"),
                "calories": data.get("calories"),
                "dietary_tags": data.get("dietary_tags"),
            })

    if not results:
        return f"No recipes found matching query '{query}' and cuisine '{cuisine}'."
    return json.dumps(results, indent=2)


def get_recipe_details(recipe_id: str) -> str:
    """Fetches complete recipe details including ingredients and preparation instructions.

    Args:
        recipe_id: The unique ID of the recipe (e.g. 'lemon-herb-chicken', 'creamy-tuscan-pasta').

    Returns:
        A JSON string with full recipe details or an error message if not found.
    """
    db = firestore.Client(project=FIRESTORE_PROJECT_ID)
    doc_ref = db.collection("recipes").document(recipe_id)
    doc = doc_ref.get()

    if not doc.exists:
        return f"Recipe with ID '{recipe_id}' not found."
    return json.dumps(doc.to_dict(), indent=2)


def add_recipe(
    recipe_id: str,
    title: str,
    cuisine: str,
    ingredients: list[str],
    instructions: str,
    prep_time_minutes: int,
    calories: int,
    dietary_tags: list[str] = None,
) -> str:
    """Adds a new recipe or updates an existing recipe in Firestore.

    Args:
        recipe_id: A unique snake_case slug identifier (e.g., 'berry-smoothie-bowl').
        title: The display title of the recipe.
        cuisine: Cuisine style (e.g., American, Italian, Mexican, Fusion).
        ingredients: List of ingredient strings with measurements.
        instructions: Step-by-step cooking instructions.
        prep_time_minutes: Preparation time in minutes.
        calories: Estimated total calories per serving.
        dietary_tags: Optional list of dietary tags (e.g. ['vegan', 'gluten-free']).

    Returns:
        A confirmation message indicating the recipe was added.
    """
    db = firestore.Client(project=FIRESTORE_PROJECT_ID)
    recipe_data = {
        "recipe_id": recipe_id,
        "title": title,
        "cuisine": cuisine,
        "ingredients": ingredients,
        "instructions": instructions,
        "prep_time_minutes": prep_time_minutes,
        "calories": calories,
        "dietary_tags": dietary_tags or [],
    }
    db.collection("recipes").document(recipe_data["recipe_id"]).set(recipe_data)
    return f"Successfully added recipe '{title}' (ID: {recipe_id}) to Firestore."


def scale_recipe_yield(
    recipe_id: str, target_servings: int, original_servings: int = 4
) -> str:
    """Rescales recipe ingredient quantities for a target number of servings.

    Args:
        recipe_id: The ID of the recipe to scale (e.g. 'creamy-tuscan-pasta').
        target_servings: Desired number of servings to scale the recipe to (e.g. 8).
        original_servings: Base number of servings for the stored recipe (default 4).

    Returns:
        A JSON string with the scaled recipe title, target servings, and adjusted ingredient list.
    """
    db = firestore.Client(project=FIRESTORE_PROJECT_ID)
    doc_ref = db.collection("recipes").document(recipe_id)
    doc = doc_ref.get()

    if not doc.exists:
        return f"Recipe with ID '{recipe_id}' not found."

    data = doc.to_dict()
    scaling_factor = target_servings / float(original_servings)
    scaled_ingredients = []

    for item in data.get("ingredients", []):

        def multiply_match(m):
            val = float(m.group(0))
            scaled = val * scaling_factor
            return f"{scaled:.2f}".rstrip("0").rstrip(".")

        scaled_item = re.sub(r"^\d+(\.\d+)?", multiply_match, item)
        scaled_ingredients.append(scaled_item)

    return json.dumps(
        {
            "recipe_id": recipe_id,
            "title": data.get("title"),
            "target_servings": target_servings,
            "scaling_factor": round(scaling_factor, 2),
            "scaled_ingredients": scaled_ingredients,
        },
        indent=2,
    )


def search_external_recipes(query: str) -> str:
    """Searches the public TheMealDB API for global recipe ideas and instructions.

    Args:
        query: Search term for a meal, ingredient, or dish name (e.g. 'Penne', 'Chicken', 'Taco').

    Returns:
        A JSON string containing matching recipes from the public meal database.
    """
    api_key = os.getenv("MEALDB_API_KEY", "1")
    url = f"https://www.themealdb.com/api/json/v1/{api_key}/search.php?s={urllib.parse.quote(query)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))

        meals = data.get("meals")
        if not meals:
            return f"No global recipes found for '{query}'."

        results = []
        for meal in meals[:3]:  # Top 3 matches
            ingredients = []
            for i in range(1, 21):
                ing = meal.get(f"strIngredient{i}")
                meas = meal.get(f"strMeasure{i}")
                if ing and ing.strip():
                    ingredients.append(f"{meas.strip() if meas else ''} {ing.strip()}".strip())

            results.append({
                "meal_id": meal.get("idMeal"),
                "name": meal.get("strMeal"),
                "category": meal.get("strCategory"),
                "area": meal.get("strArea"),
                "instructions": meal.get("strInstructions"),
                "thumbnail": meal.get("strMealThumb"),
                "ingredients": ingredients,
            })

        return json.dumps(results, indent=2)
    except Exception as e:
        return f"Error fetching public recipe data: {str(e)}"


def geocode_address(address: str) -> str:
    """Converts a street address or location name into geographic coordinates (latitude and longitude).

    Args:
        address: The address or place name to geocode (e.g., '1600 Amphitheatre Parkway, Mountain View, CA').

    Returns:
        A JSON string containing formatted address, latitude, and longitude.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY environment variable is not set."

    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(address)}&key={api_key}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))

        if data.get("status") != "OK" or not data.get("results"):
            return f"Geocoding failed for address '{address}'. Status: {data.get('status')}"

        result = data["results"][0]
        location = result["geometry"]["location"]
        return json.dumps({
            "address": result.get("formatted_address"),
            "latitude": location.get("lat"),
            "longitude": location.get("lng"),
        }, indent=2)
    except Exception as e:
        return f"Error executing geocoding: {str(e)}"


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "supermarket",
    radius_meters: float = 3000.0,
) -> str:
    """Finds nearby places (e.g. supermarkets, grocery stores, restaurants) around a given coordinate using Places API (New).

    Args:
        latitude: Latitude coordinate of the center location.
        longitude: Longitude coordinate of the center location.
        place_type: Type of place to search for (e.g. 'supermarket', 'grocery_store', 'restaurant').
        radius_meters: Search radius in meters (default 3000 meters).

    Returns:
        A JSON string containing a list of matching nearby places with name, address, and location.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY environment variable is not set."

    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
    }
    payload = {
        "includedTypes": [place_type],
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": latitude,
                    "longitude": longitude,
                },
                "radius": radius_meters,
            }
        },
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))

        places = data.get("places", [])
        if not places:
            return f"No nearby places of type '{place_type}' found within {radius_meters}m."

        results = []
        for p in places[:5]:  # Top 5 places
            results.append({
                "name": p.get("displayName", {}).get("text"),
                "address": p.get("formattedAddress"),
                "location": p.get("location"),
            })

        return json.dumps(results, indent=2)
    except Exception as e:
        return f"Error finding nearby places: {str(e)}"


def generate_recipe_visual(
    prompt: str,
    recipe_name: str = "recipe_visual",
    tool_context: ToolContext = None,
) -> str:
    """Generates an image for a recipe item using gemini-3.1-flash-lite-image in global region, saves as an artifact, and uploads to GCS.

    Args:
        prompt: Detailed visual description of the recipe dish to generate.
        recipe_name: Short identifier/name for the recipe (e.g. 'lemon_herb_chicken').

    Returns:
        The public Cloud Storage HTTPS URL (https://storage.googleapis.com/<bucket>/<object>) of the generated image.
    """
    client = genai.Client(
        vertexai=True,
        project=FIRESTORE_PROJECT_ID,
        location="global",
    )

    response = client.models.generate_content(
        model="gemini-3.1-flash-lite-image",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"]
        ),
    )

    image_bytes = None
    for candidate in response.candidates:
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.inline_data and part.inline_data.data:
                    image_bytes = part.inline_data.data
                    break

    if not image_bytes:
        return "Error: Could not extract generated image bytes."

    clean_name = re.sub(r"[^a-zA-Z0-9_-]", "_", recipe_name.lower().replace(" ", "_"))
    filename = f"{clean_name}.jpg"

    # (1) Save artifact for Playground Artifacts panel
    if tool_context:
        artifact_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

    # (2) Upload same image bytes to public Cloud Storage bucket
    storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(f"recipes/{filename}")
    blob.upload_from_string(image_bytes, content_type="image/jpeg")

    public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/recipes/{filename}"
    return public_url


def generate_recipe_video(
    prompt: str,
    recipe_name: str = "recipe_video",
    tool_context: ToolContext = None,
) -> str:
    """Generates a short video for a recipe item using gemini-omni-flash-preview in global region, saves as an artifact, and uploads to GCS.

    Args:
        prompt: Visual prompt describing the recipe dish or cooking action video to generate.
        recipe_name: Short identifier/name for the recipe (e.g. 'sizzling_garlic').

    Returns:
        The public Cloud Storage HTTPS URL (https://storage.googleapis.com/<bucket>/<object>) of the generated video.
    """
    client = genai.Client(
        vertexai=True,
        project=FIRESTORE_PROJECT_ID,
        location="global",
    )

    interaction = client.interactions.create(
        model="gemini-omni-flash-preview",
        input=prompt,
    )

    video_bytes = None
    mime_type = "video/mp4"

    if hasattr(interaction, "output_video") and interaction.output_video:
        ov = interaction.output_video
        if getattr(ov, "data", None):
            data = ov.data
            video_bytes = data if isinstance(data, bytes) else base64.b64decode(data)
        if getattr(ov, "mime_type", None):
            mime_type = ov.mime_type

    if not video_bytes:
        return "Error: Could not extract generated video bytes from interaction."

    clean_name = re.sub(r"[^a-zA-Z0-9_-]", "_", recipe_name.lower().replace(" ", "_"))
    filename = f"{clean_name}.mp4"

    # (1) Save artifact for Playground Artifacts panel
    if tool_context:
        artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

    # (2) Upload same video bytes to public Cloud Storage bucket
    storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(f"recipes/{filename}")
    blob.upload_from_string(video_bytes, content_type=mime_type)

    public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/recipes/{filename}"
    return public_url


# A2UI Schema Manager setup with BasicCatalog (version 0.8)
a2ui_schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_instruction = a2ui_schema_manager.generate_system_prompt(
    role_description=(
        "Recipe Assistant, a personal chef and culinary agent. "
        "Help users discover recipes from Firestore, view detailed cooking steps, "
        "filter by dietary requirements or cuisine, rescale ingredient yields for different portion sizes, "
        "search global recipe ideas via the external meal database API, geocode addresses to coordinates, "
        "find nearby grocery stores and supermarkets using Google Maps & Places APIs, "
        "generate food visuals using Gemini, generate cooking video clips using Gemini Omni, "
        "run Python code in a safe sandbox for complex numerical calculations, "
        "and add new custom recipes."
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects.\n"
        "IMPORTANT MEMORY INSTRUCTION: Always pay strict attention to all user allergies and dietary restrictions "
        "(e.g., peanuts, shellfish, gluten, dairy, tree nuts). Remember any allergies stated by the user across conversations via Memory Bank, "
        "and automatically filter out or flag allergen-containing ingredients when searching, scaling, or recommending recipes."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=a2ui_instruction,
    code_executor=AgentEngineSandboxCodeExecutor(
        agent_engine_resource_name=AGENT_ENGINE_RESOURCE_NAME
    ),
    tools=[
        PreloadMemoryTool(),
        search_recipes,
        get_recipe_details,
        add_recipe,
        scale_recipe_yield,
        search_external_recipes,
        geocode_address,
        find_nearby_places,
        generate_recipe_visual,
        generate_recipe_video,
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)

