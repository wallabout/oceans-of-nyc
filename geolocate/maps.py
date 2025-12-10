"""Map generation using OpenStreetMap tiles via staticmap."""

from pathlib import Path
from staticmap import StaticMap, CircleMarker


class MapGenerator:
    """Generate static map images using OpenStreetMap tiles."""

    def __init__(self, cache_dir: str = "maps"):
        """
        Initialize the map generator.

        Args:
            cache_dir: Directory to cache generated map images
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

    def generate_map(
        self,
        latitude: float,
        longitude: float,
        zoom: int = 15,
        width: int = 600,
        height: int = 400,
        output_path: str = None
    ) -> str:
        """
        Generate a static map image centered on the given coordinates.

        Uses the staticmap library to fetch and stitch OpenStreetMap tiles.

        Args:
            latitude: Center latitude
            longitude: Center longitude
            zoom: Zoom level (1-18, higher is more zoomed in)
            width: Image width in pixels
            height: Image height in pixels
            output_path: Optional custom output path. If not provided, saves to cache_dir

        Returns:
            Path to the generated map image
        """
        # Create a static map
        m = StaticMap(width, height)

        # Add a marker at the location
        marker = CircleMarker((longitude, latitude), 'red', 12)
        m.add_marker(marker)

        # Determine output path
        if output_path is None:
            filename = f"map_{latitude}_{longitude}_{zoom}.png"
            output_path = self.cache_dir / filename
        else:
            output_path = Path(output_path)

        # Render the map image
        image = m.render(zoom=zoom)
        image.save(str(output_path))

        return str(output_path)

    def generate_sighting_map(
        self,
        latitude: float,
        longitude: float,
        license_plate: str
    ) -> str:
        """
        Generate a map image for a sighting.

        Creates a map centered on the sighting location with optimal settings
        for posting to social media.

        Args:
            latitude: Sighting latitude
            longitude: Sighting longitude
            license_plate: License plate (used for filename)

        Returns:
            Path to the generated map image
        """
        # Use a custom filename based on the license plate
        filename = f"sighting_{license_plate}_{latitude}_{longitude}.png"
        output_path = self.cache_dir / filename

        # Generate with optimal settings for social media
        return self.generate_map(
            latitude=latitude,
            longitude=longitude,
            zoom=16,  # Good detail level for city streets
            width=800,
            height=600,
            output_path=str(output_path)
        )


# Convenience function for simple usage
def generate_map(latitude: float, longitude: float, output_path: str) -> str:
    """
    Generate a map image at the given coordinates.

    Args:
        latitude: Center latitude
        longitude: Center longitude
        output_path: Where to save the map image

    Returns:
        Path to the generated map image
    """
    generator = MapGenerator()
    return generator.generate_map(
        latitude=latitude,
        longitude=longitude,
        zoom=16,
        width=800,
        height=600,
        output_path=output_path
    )
