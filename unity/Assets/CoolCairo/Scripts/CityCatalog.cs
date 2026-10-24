using UnityEngine;

namespace CoolCairo
{
    // The cities on the globe. Live cities have an analysed district: Cairo's district.json is
    // built into the scenes; the others are Resources/Districts/<key>.json, exported by the same
    // pipeline with their own config (analysis/config/aoi_<key>.yaml). The choice made on the
    // globe carries into the district scene through Selected / SelectedJson.
    public static class CityCatalog
    {
        public class City
        {
            public string Key, Name, District;
            public float Lat, Lon;   // the district's centre for live cities
            public bool Live;
            public string Label => Live ? $"{Name} — {District}" : Name;
        }

        public static readonly City[] All =
        {
            new City { Key = "cairo", Name = "Cairo", District = "Nasr City", Lat = 30.059f, Lon = 31.336f, Live = true },
            new City { Key = "casablanca", Name = "Casablanca", District = "Hay Mohammadi", Lat = 33.584f, Lon = -7.557f, Live = true },
            new City { Key = "algiers", Name = "Algiers", District = "Bab El Oued", Lat = 36.782f, Lon = 3.048f, Live = true },
            new City { Key = "dubai", Name = "Dubai", District = "Al Karama", Lat = 25.248f, Lon = 55.305f, Live = true },
            new City { Key = "riyadh", Name = "Riyadh", District = "Al Malaz", Lat = 24.656f, Lon = 46.728f, Live = true },
            new City { Key = "abudhabi", Name = "Abu Dhabi", Lat = 24.45f, Lon = 54.38f },
            new City { Key = "doha", Name = "Doha", Lat = 25.29f, Lon = 51.53f },
            new City { Key = "kuwait", Name = "Kuwait City", Lat = 29.38f, Lon = 47.99f },
            new City { Key = "muscat", Name = "Muscat", Lat = 23.59f, Lon = 58.41f },
            new City { Key = "amman", Name = "Amman", Lat = 31.95f, Lon = 35.93f },
            new City { Key = "beirut", Name = "Beirut", Lat = 33.89f, Lon = 35.50f },
            new City { Key = "baghdad", Name = "Baghdad", Lat = 33.31f, Lon = 44.36f },
            new City { Key = "tunis", Name = "Tunis", Lat = 36.81f, Lon = 10.18f },
        };

        // The city chosen on the globe; null until one is chosen (the district scene then shows Cairo).
        public static City Selected { get; private set; }
        public static string SelectedJson { get; private set; }

        public static bool CairoSelected => Selected == null || Selected.Key == "cairo";

        // A city's district.json text: Cairo's from the scene's own asset, the others from Resources.
        public static string Json(City city, TextAsset cairo) =>
            city.Key == "cairo" ? cairo.text : Resources.Load<TextAsset>("Districts/" + city.Key)?.text;

        public static void Select(City city, string json)
        {
            Selected = city;
            SelectedJson = json;
        }
    }
}
