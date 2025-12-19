# Validate Module

This module handles NYC TLC (Taxi & Limousine Commission) vehicle data for verifying Fisker Ocean vehicles operating as for-hire vehicles in NYC.

## Data Source

The TLC vehicle data comes from NYC Open Data:
- **Dataset**: [For Hire Vehicles (FHV) - Active](https://data.cityofnewyork.us/Transportation/For-Hire-Vehicles-FHV-Active/8wbx-tsch/about_data)
- **Updates**: Nightly
- **Records**: 100,000+ active for-hire vehicles in NYC

## Importing TLC Data

Download the latest CSV from the NYC Open Data portal and import it:

```bash
uv run python main.py import-tlc data/For_Hire_Vehicles_(FHV)_-_Active_YYYYMMDD.csv
```

**Example output:**
```
✓ Successfully imported 104,821 TLC vehicle records
  - Total vehicles in database: 104,821
```

## Looking up Vehicle Information

Once imported, you can look up any TLC vehicle by license plate:

```bash
uv run python main.py lookup-tlc T731580C
```

**Note:** The lookup uses the PostgreSQL database configured via `DATABASE_URL` environment variable (loaded from `.env` file).

Alternatively, you can use the Python API directly:

```bash
uv run python -c "
from validate import TLCDatabase
import os

db = TLCDatabase()
vehicle = db.get_vehicle_by_plate('T731580C')

if vehicle:
    print(f'\nTLC Vehicle Information for T731580C:\n')
    print(f'  Active: {vehicle[1]}')
    print(f'  Vehicle License Number: {vehicle[2]}')
    print(f'  Owner Name: {vehicle[3]}')
    print(f'  License Type: {vehicle[4]}')
    print(f'  VIN: {vehicle[8]}')
    print(f'  Vehicle Year: {vehicle[12]}')
    print(f'  Base Name: {vehicle[14]}')
    print(f'  Base Type: {vehicle[15]}')
    print(f'  Base Address: {vehicle[19]}')
else:
    print('No vehicle found')
"
```

**Example output:**
```
TLC Vehicle Information for T731580C:

  Active: YES
  Vehicle License Number: 5801620
  Owner Name: AMERICAN UNITED TRANSPORTATION INC
  License Type: FOR HIRE VEHICLE
  VIN: VCF1ZBU27PG004131
  Vehicle Year: 2023
  Base Name: UBER USA, LLC
  Base Type: BLACK-CAR
  Base Address: 1515 THIRD STREET SAN FRANCISCO CA 94158
```

This data helps verify that spotted vehicles are legitimate TLC-registered Fisker Oceans operating in NYC.

## Features

- **TLC Data Import** - Import and query 100,000+ NYC for-hire vehicle records
- **Vehicle Lookup** - Verify license plates against official TLC database
- **Wildcard Plate Search** - Find plates with partial matches (e.g., `T73**580C`)
- **TLC Validation** - Validates entered plates against the TLC database during batch processing
- **Fisker Filtering** - Filters database to only Fisker vehicles (VIN starts with `VCF1`)

## Module Structure

- `tlc.py` - TLC database operations and data import
- `matcher.py` - Wildcard pattern matching for license plates
- `__init__.py` - Public API exports
