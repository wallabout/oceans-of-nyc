"""Reverse geocoding using Nominatim (OpenStreetMap)."""

import requests
import time
from typing import Optional


class Geocoder:
    """Reverse geocoding using Nominatim (OpenStreetMap)."""

    # NYC borough name mapping
    BOROUGH_MAP = {
        'Kings': 'Brooklyn',
        'Kings County': 'Brooklyn',
        'Queens': 'Queens',
        'Queens County': 'Queens',
        'New York': 'Manhattan',
        'New York County': 'Manhattan',
        'Bronx': 'The Bronx',
        'Bronx County': 'The Bronx',
        'Richmond': 'Staten Island',
        'Richmond County': 'Staten Island'
    }

    def __init__(self):
        """Initialize the geocoder with Nominatim API."""
        self.reverse_url = "https://nominatim.openstreetmap.org/reverse"
        self.search_url = "https://nominatim.openstreetmap.org/search"
        # Nominatim requires a user agent
        self.user_agent = "FiskerOceanSpotterBot/1.0"
        self.last_request_time = 0
        # Nominatim rate limit: 1 request per second
        self.rate_limit_delay = 1.0

    def _respect_rate_limit(self):
        """Ensure we don't exceed Nominatim's 1 request/second rate limit."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - time_since_last)
        self.last_request_time = time.time()

    def reverse_geocode(self, latitude: float, longitude: float) -> Optional[dict]:
        """
        Reverse geocode coordinates to get address information.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate

        Returns:
            Dictionary with address components, or None if lookup fails
        """
        self._respect_rate_limit()

        params = {
            'lat': latitude,
            'lon': longitude,
            'format': 'json',
            'addressdetails': 1,
            'zoom': 18  # Higher zoom for more detailed addresses
        }

        headers = {
            'User-Agent': self.user_agent
        }

        try:
            response = requests.get(
                self.reverse_url,
                params=params,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            # If geocoding fails, return None and we'll fall back to coordinates
            return None

    def get_neighborhood_name(self, latitude: float, longitude: float) -> Optional[str]:
        """
        Get a human-readable neighborhood name for NYC coordinates.

        Returns a formatted string like "Astoria, Queens" or "Fort Greene, Brooklyn"

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate

        Returns:
            Formatted neighborhood string, or None if lookup fails
        """
        data = self.reverse_geocode(latitude, longitude)

        if not data or 'address' not in data:
            return None

        address = data['address']

        # Try to extract neighborhood and borough from the address
        # Nominatim returns different fields depending on the location
        # Common fields: neighbourhood, suburb, city_district, borough, city

        neighborhood = (
            address.get('neighbourhood') or
            address.get('suburb') or
            address.get('hamlet') or
            address.get('village')
        )

        borough = (
            address.get('city_district') or
            address.get('borough') or
            address.get('county')
        )

        # Format the result
        parts = []
        if neighborhood:
            parts.append(neighborhood)
        if borough:
            # Map NYC county names to common borough names
            borough_clean = self.BOROUGH_MAP.get(borough, borough)
            # Also handle any remaining "Borough of" or "County" suffix
            borough_clean = borough_clean.replace('Borough of ', '').replace(' County', '')
            parts.append(borough_clean)

        if parts:
            return ', '.join(parts)

        # Fallback to city if we can't get neighborhood/borough
        city = address.get('city') or address.get('town')
        if city:
            return city

        return None

    def geocode_address(self, address: str) -> Optional[tuple[float, float]]:
        """
        Convert an address string to coordinates (forward geocoding).

        Args:
            address: Address string (street address or neighborhood in NYC)

        Returns:
            Tuple of (latitude, longitude) or None if lookup fails
        """
        self._respect_rate_limit()

        # Add "New York City" to help with geocoding
        search_query = address
        if "new york" not in address.lower() and "nyc" not in address.lower():
            search_query = f"{address}, New York City, NY"

        params = {
            'q': search_query,
            'format': 'json',
            'limit': 1,
            'countrycodes': 'us'
        }

        headers = {
            'User-Agent': self.user_agent
        }

        try:
            response = requests.get(
                self.search_url,
                params=params,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            results = response.json()

            if results and len(results) > 0:
                lat = float(results[0]['lat'])
                lon = float(results[0]['lon'])
                return (lat, lon)

            return None
        except Exception as e:
            print(f"Error geocoding address: {e}")
            return None


# Convenience functions for simple usage
def reverse_geocode(latitude: float, longitude: float) -> str:
    """
    Get a human-readable location name for coordinates.

    Returns neighborhood name or "Unknown location" if lookup fails.
    """
    geocoder = Geocoder()
    result = geocoder.get_neighborhood_name(latitude, longitude)
    return result or "Unknown location"


def geocode_address(address: str) -> Optional[tuple[float, float]]:
    """
    Convert an address to coordinates.

    Returns (latitude, longitude) or None if lookup fails.
    """
    geocoder = Geocoder()
    return geocoder.geocode_address(address)
