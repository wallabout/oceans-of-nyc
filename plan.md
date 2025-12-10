# Oceans of NYC Architecture Plan

See also: [architecture diagram](./architecture.png)

## Infrastructure

| Component | Service | Status |
|-----------|---------|--------|
| Compute | Modal (serverless) | ✅ Deployed |
| Database | Neon PostgreSQL | ✅ Connected |
| Image Storage | Modal Volume | ✅ Configured |
| SMS/MMS | Twilio | 🔲 Credentials ready |

---

## Modules

### Process (`process/`)
**Scope**: Orchestrate all modules, coordinate sighting workflow

**Systems**: Modal, Modal Volumes, Neon, other modules

**Functions**:
- [ ] `process_sighting(image, phone_number)` - Main entry point for new sightings
- [x] `batch_post(limit, dry_run)` - Post multiple unposted sightings
- [x] `scheduled_post()` - Cron trigger for batch posting

**Files to create**:
- `process/orchestrator.py` - Main workflow logic

**Current location**: `modal_app.py` (batch_post, scheduled_batch_post)

---

### Chat (`chat/`)
**Scope**: SMS/MMS user experience for collecting sightings

**Systems**: Twilio

**Functions**:
- [ ] `sms_webhook(request)` - Receive incoming SMS/MMS from Twilio
- [ ] `get_session(phone_number)` - Get or create conversation state
- [ ] `handle_message(session, message, media)` - Process user input
- [ ] `send_response(phone_number, message)` - Send SMS reply
- [ ] `prompt_for_plate(session)` - Ask for license plate
- [ ] `prompt_for_confirmation(session, matches)` - Confirm plate match

**Files to create**:
- `chat/twilio_webhook.py` - Modal web endpoint for Twilio
- `chat/session.py` - Conversation state management
- `chat/messages.py` - Response templates

**Database additions needed**:
- `chat_sessions` table (phone_number, state, current_sighting_id, created_at, updated_at)

---

### Validate (`validate/`)
**Scope**: License plate validation against TLC database

**Systems**: NYC TLC Database

**Functions**:
- [x] `import_tlc_data(csv_path)` - Import TLC CSV data
- [x] `filter_fisker_vehicles()` - Keep only Fisker VINs
- [x] `get_tlc_vehicle_by_plate(plate)` - Exact lookup
- [x] `search_plates_wildcard(pattern)` - Fuzzy matching with `*`
- [x] `get_potential_matches(partial_plate)` - Smart suggestions for partial plates
- [x] `validate_plate(plate)` - Returns (is_valid, vehicle_record)
- [x] `find_similar_plates(plate)` - Find plates differing by 1-2 characters

**Files**:
- `validate/tlc.py` - TLC database operations ✅
- `validate/matcher.py` - Plate matching logic ✅

---

### Geolocate (`geolocate/`)
**Scope**: Location processing and visualization

**Systems**: OpenStreetMap, Nominatim, staticmap

**Functions**:
- [x] `reverse_geocode(lat, lon)` - Get neighborhood name
- [x] `generate_map(lat, lon, output_path)` - Create map image
- [x] `extract_gps_from_exif(image_path)` - Get coordinates from photo
- [x] `extract_timestamp_from_exif(image_path)` - Get timestamp from photo

**Files**:
- `geolocate/geocoding.py` - Reverse geocoding ✅
- `geolocate/maps.py` - Map generation ✅
- `geolocate/exif.py` - EXIF extraction ✅

---

### Post (`post/`)
**Scope**: Social media publishing

**Systems**: Bluesky AT Protocol

**Functions**:
- [x] `create_post(text, images, alts)` - Post to Bluesky
- [x] `upload_image(path, alt)` - Upload and compress image
- [x] `format_sighting_text(...)` - Generate post text
- [x] `compress_image(path)` - Fit within size limits

**Files**:
- `post/bluesky.py` - Bluesky client ✅

---

### Database (`database/`)
**Scope**: Core data models and operations

**Systems**: Neon PostgreSQL

**Tables**:
- [x] `sightings` - Individual sighting records
- [x] `tlc_vehicles` - TLC Fisker vehicle registry
- [ ] `chat_sessions` - SMS conversation state

**Functions**:
- [x] `add_sighting(...)` - Create new sighting
- [x] `get_unposted_sightings()` - Query for posting
- [x] `mark_as_posted(id, uri)` - Update after post
- [x] `get_sighting_count(plate)` - Stats per vehicle
- [x] `get_unique_sighted_count()` - Unique plates spotted
- [x] `get_unique_posted_count()` - Unique plates posted

**Files**:
- `database/models.py` - Core sighting operations ✅
- `database/sessions.py` - Chat session operations (planned for Phase 2)

---

## File Structure (Target)

```
bluesky-oceansofnyc/
├── modal_app.py              # Entry point, function definitions
├── process/
│   ├── __init__.py
│   └── orchestrator.py       # process_sighting workflow
├── chat/
│   ├── __init__.py
│   ├── twilio_webhook.py     # SMS endpoint
│   ├── session.py            # Conversation state
│   └── messages.py           # Response templates
├── validate/
│   ├── __init__.py
│   ├── tlc.py                # TLC database ops
│   └── matcher.py            # Plate matching
├── geolocate/
│   ├── __init__.py
│   ├── geocoding.py          # Reverse geocode
│   ├── maps.py               # Map generation
│   └── exif.py               # EXIF extraction
├── post/
│   ├── __init__.py
│   └── bluesky.py            # Bluesky client
├── database/
│   ├── __init__.py
│   ├── models.py             # Sightings, TLC
│   └── sessions.py           # Chat sessions
└── tests/                    # Future
```

---

## Next Steps

### Phase 1: Code Reorganization ✅ COMPLETE
- [x] Create module directories with `__init__.py`
- [x] Move `geocoding.py` → `geolocate/geocoding.py`
- [x] Move `map_generator.py` → `geolocate/maps.py`
- [x] Move `exif_utils.py` → `geolocate/exif.py`
- [x] Move `bluesky_client.py` → `post/bluesky.py`
- [x] Split `database.py` → `database/models.py` + `validate/tlc.py` + `validate/matcher.py`
- [x] Update `modal_app.py` imports
- [x] Test deployment

### Phase 2: Chat Module
- [ ] Create `chat_sessions` table in Neon
- [ ] Add Twilio secret to Modal
- [ ] Implement `chat/twilio_webhook.py` with Modal web endpoint
- [ ] Implement `chat/session.py` state machine
- [ ] Implement `chat/messages.py` response templates
- [ ] Deploy and configure Twilio webhook URL

### Phase 3: Process Orchestration
- [ ] Create `process/orchestrator.py`
- [ ] Implement `process_sighting()` to coordinate all modules
- [ ] Refactor `batch_post` to use orchestrator
- [ ] Add Modal queue for async processing (optional)
