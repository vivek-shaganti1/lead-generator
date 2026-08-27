"""Business categories we target, expressed once and translated per provider.

These are the verticals where a missing website costs the owner real money and
where a small brochure site is an easy, honest sell.
"""
from __future__ import annotations

# key -> (OSM tag filters, Google Places "includedTypes", human label)
CATEGORY_PRESETS: dict[str, dict] = {
    "restaurant":   {"osm": [("amenity", "restaurant")], "google": ["restaurant"], "label": "Restaurants"},
    "cafe":         {"osm": [("amenity", "cafe")], "google": ["cafe"], "label": "Cafés"},
    "bakery":       {"osm": [("shop", "bakery")], "google": ["bakery"], "label": "Bakeries"},
    "bar":          {"osm": [("amenity", "bar"), ("amenity", "pub")], "google": ["bar"], "label": "Bars & Pubs"},
    "hotel":        {"osm": [("tourism", "hotel"), ("tourism", "guest_house")], "google": ["lodging"], "label": "Hotels & Guesthouses"},
    "salon":        {"osm": [("shop", "hairdresser"), ("shop", "beauty")], "google": ["hair_care", "beauty_salon"], "label": "Salons & Beauty"},
    "gym":          {"osm": [("leisure", "fitness_centre")], "google": ["gym"], "label": "Gyms & Fitness"},
    "dentist":      {"osm": [("amenity", "dentist")], "google": ["dentist"], "label": "Dentists"},
    "doctor":       {"osm": [("amenity", "doctors"), ("amenity", "clinic")], "google": ["doctor"], "label": "Clinics & Doctors"},
    "veterinary":   {"osm": [("amenity", "veterinary")], "google": ["veterinary_care"], "label": "Veterinary"},
    "pharmacy":     {"osm": [("amenity", "pharmacy")], "google": ["pharmacy"], "label": "Pharmacies"},
    "lawyer":       {"osm": [("office", "lawyer")], "google": ["lawyer"], "label": "Law Firms"},
    "accountant":   {"osm": [("office", "accountant")], "google": ["accounting"], "label": "Accountants"},
    "estate_agent": {"osm": [("office", "estate_agent")], "google": ["real_estate_agency"], "label": "Estate Agents"},
    "insurance":    {"osm": [("office", "insurance")], "google": ["insurance_agency"], "label": "Insurance Agents"},
    "car_repair":   {"osm": [("shop", "car_repair")], "google": ["car_repair"], "label": "Auto Repair"},
    "car_dealer":   {"osm": [("shop", "car")], "google": ["car_dealer"], "label": "Car Dealers"},
    "plumber":      {"osm": [("craft", "plumber")], "google": ["plumber"], "label": "Plumbers"},
    "electrician":  {"osm": [("craft", "electrician")], "google": ["electrician"], "label": "Electricians"},
    "carpenter":    {"osm": [("craft", "carpenter")], "google": [], "label": "Carpenters"},
    "builder":      {"osm": [("craft", "builder"), ("office", "construction_company")], "google": ["general_contractor"], "label": "Builders & Contractors"},
    "painter":      {"osm": [("craft", "painter")], "google": ["painter"], "label": "Painters"},
    "photographer": {"osm": [("craft", "photographer"), ("shop", "photo")], "google": [], "label": "Photographers"},
    "florist":      {"osm": [("shop", "florist")], "google": ["florist"], "label": "Florists"},
    "furniture":    {"osm": [("shop", "furniture")], "google": ["furniture_store"], "label": "Furniture Stores"},
    "clothes":      {"osm": [("shop", "clothes")], "google": ["clothing_store"], "label": "Clothing Stores"},
    "jewelry":      {"osm": [("shop", "jewelry")], "google": ["jewelry_store"], "label": "Jewellers"},
    "hardware":     {"osm": [("shop", "hardware"), ("shop", "doityourself")], "google": ["hardware_store"], "label": "Hardware Stores"},
    "optician":     {"osm": [("shop", "optician")], "google": [], "label": "Opticians"},
    "laundry":      {"osm": [("shop", "laundry"), ("shop", "dry_cleaning")], "google": ["laundry"], "label": "Laundry & Dry Cleaning"},
    "travel_agency": {"osm": [("shop", "travel_agency")], "google": ["travel_agency"], "label": "Travel Agents"},
    "driving_school": {"osm": [("amenity", "driving_school")], "google": [], "label": "Driving Schools"},
    "childcare":    {"osm": [("amenity", "childcare"), ("amenity", "kindergarten")], "google": [], "label": "Childcare"},
    "tutoring":     {"osm": [("amenity", "language_school"), ("office", "educational_institution")], "google": ["school"], "label": "Tutors & Schools"},
    "pet_shop":     {"osm": [("shop", "pet"), ("shop", "pet_grooming")], "google": ["pet_store"], "label": "Pet Shops & Grooming"},
    "butcher":      {"osm": [("shop", "butcher")], "google": [], "label": "Butchers"},
    "greengrocer":  {"osm": [("shop", "greengrocer"), ("shop", "convenience")], "google": ["grocery_store"], "label": "Grocers"},
    "catering":     {"osm": [("craft", "caterer"), ("shop", "caterer")], "google": ["meal_delivery"], "label": "Caterers"},
    "event_venue":  {"osm": [("amenity", "events_venue")], "google": [], "label": "Event Venues"},
    "spa":          {"osm": [("leisure", "spa"), ("shop", "massage")], "google": ["spa"], "label": "Spas & Massage"},
}

DEFAULT_CATEGORIES = ["restaurant", "cafe", "salon", "gym", "car_repair", "dentist", "plumber"]


def resolve(categories: list[str] | None) -> list[str]:
    """Validate requested categories, falling back to a sensible default set."""
    if not categories:
        return list(DEFAULT_CATEGORIES)
    unknown = [c for c in categories if c not in CATEGORY_PRESETS]
    if unknown:
        raise ValueError(f"Unknown categories: {', '.join(sorted(unknown))}")
    # de-duplicate while preserving the caller's order
    return list(dict.fromkeys(categories))


def osm_filters(categories: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for c in categories:
        out.extend(CATEGORY_PRESETS[c]["osm"])
    return list(dict.fromkeys(out))


def google_types(categories: list[str]) -> list[str]:
    out: list[str] = []
    for c in categories:
        out.extend(CATEGORY_PRESETS[c]["google"])
    return list(dict.fromkeys(out))


def label_for_osm_tags(tags: dict) -> str | None:
    """Reverse map an OSM element back onto our category key."""
    for key, preset in CATEGORY_PRESETS.items():
        for tag_k, tag_v in preset["osm"]:
            if tags.get(tag_k) == tag_v:
                return key
    for tag_k in ("shop", "amenity", "craft", "office", "leisure", "tourism"):
        if tag_k in tags:
            return str(tags[tag_k])
    return None
