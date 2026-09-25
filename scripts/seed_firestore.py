"""Seed script for Firestore recipes collection."""

from google.cloud import firestore

# IMPORTANT: Hardcoded Project ID string
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-02-d6cd529c0ad9"

SEED_RECIPES = [
    {
        "recipe_id": "lemon-herb-chicken",
        "title": "Lemon Herb Roasted Chicken",
        "cuisine": "Mediterranean",
        "ingredients": [
            "2 lbs chicken thighs",
            "2 lemons, juiced and zested",
            "3 cloves garlic, minced",
            "2 tbsp olive oil",
            "1 tbsp fresh rosemary",
            "Salt and black pepper to taste",
        ],
        "instructions": "Marinate chicken with lemon juice, garlic, olive oil, and rosemary for 30 mins. Roast at 400°F (200°C) for 35 minutes until golden.",
        "prep_time_minutes": 45,
        "calories": 480,
        "dietary_tags": ["gluten-free", "low-carb", "high-protein"],
    },
    {
        "recipe_id": "creamy-tuscan-pasta",
        "title": "Creamy Tuscan Garlic Pasta",
        "cuisine": "Italian",
        "ingredients": [
            "8 oz fettuccine pasta",
            "1 cup heavy cream",
            "1/2 cup grated parmesan cheese",
            "1/2 cup sun-dried tomatoes",
            "2 cups fresh spinach",
            "3 cloves garlic, minced",
        ],
        "instructions": "Boil pasta. Sauté garlic and sun-dried tomatoes, stir in heavy cream and parmesan. Toss in spinach and pasta until coated.",
        "prep_time_minutes": 25,
        "calories": 620,
        "dietary_tags": ["vegetarian"],
    },
    {
        "recipe_id": "spicy-avocado-tacos",
        "title": "Spicy Black Bean & Avocado Tacos",
        "cuisine": "Mexican",
        "ingredients": [
            "1 can black beans, drained",
            "1 ripe avocado, sliced",
            "6 small corn tortillas",
            "1/2 cup pico de gallo",
            "1/2 tsp cumin and chili powder",
            "Fresh cilantro and lime wedges",
        ],
        "instructions": "Warm black beans with cumin and chili powder. Toast corn tortillas. Assemble with beans, avocado slices, pico de gallo, and cilantro.",
        "prep_time_minutes": 15,
        "calories": 350,
        "dietary_tags": ["vegan", "vegetarian", "gluten-free"],
    },
    {
        "recipe_id": "classic-tofu-stir-fry",
        "title": "Crispy Tofu & Vegetable Stir-Fry",
        "cuisine": "Asian",
        "ingredients": [
            "1 block extra-firm tofu, cubed",
            "2 cups broccoli florets",
            "1 red bell pepper, sliced",
            "2 tbsp low-sodium soy sauce",
            "1 tbsp sesame oil",
            "1 tsp grated ginger",
        ],
        "instructions": "Pan-fry tofu cubes in sesame oil until crispy. Toss in broccoli and bell peppers with soy sauce and ginger. Serve over brown rice.",
        "prep_time_minutes": 20,
        "calories": 310,
        "dietary_tags": ["vegan", "vegetarian", "gluten-free", "low-calorie"],
    },
]


def seed_recipes():
    print(f"Connecting to Firestore for project: {FIRESTORE_PROJECT_ID}")
    db = firestore.Client(project=FIRESTORE_PROJECT_ID)
    collection_ref = db.collection("recipes")

    for recipe in SEED_RECIPES:
        doc_ref = collection_ref.document(recipe["recipe_id"])
        doc_ref.set(recipe)
        print(f"Seeded recipe: {recipe['title']} (ID: {recipe['recipe_id']})")

    print(f"Successfully seeded {len(SEED_RECIPES)} recipes into Firestore!")


if __name__ == "__main__":
    seed_recipes()
