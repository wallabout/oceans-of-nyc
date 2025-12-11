# Chat Module

This module handles SMS/MMS interactions via Twilio webhook for community sighting submissions.

## Setup

Configure Twilio credentials in your `.env` file:

```bash
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+1234567890
```

## How It Works

The chat module provides a conversational flow for submitting sightings via SMS:

### Conversation Flow

1. **User sends photo** → Extract GPS, save to volume, ask for plate
2. **User sends plate** → Validate against TLC, ask for confirmation
3. **User confirms** → Save sighting to database

### Commands

- `HELP` - Show help message
- `CANCEL` - Cancel current submission
- `SKIP` - Skip setting a contributor name

## Usage

The webhook is deployed as part of the Modal app and receives POST requests from Twilio:

```
https://yourapp--fisker-ocean-bot-chat-sms-webhook.modal.run
```

Configure this URL in your Twilio phone number settings.

## Example Session

```
User: [sends photo]
Bot: "Great! I received your photo. What's the license plate?"

User: "T731580C"
Bot: "Found it! This is a 2023 Fisker Ocean registered to AMERICAN UNITED...
     This will be sighting #1 for this vehicle.
     Reply YES to confirm, or send a different plate number."

User: "YES"
Bot: "✓ Sighting saved! Would you like to set a name for future posts?
     Reply with your name, or SKIP to remain anonymous."

User: "@myhandle.bsky.social"
Bot: "Great! Future posts will credit you as '@myhandle.bsky.social'.
     Send a new photo anytime!"
```

## Module Structure

- `webhook.py` - Twilio webhook handler and conversation logic
- `session.py` - Session state management
- `messages.py` - Response message templates
- `__init__.py` - Public API exports

## Session States

- `IDLE` - Waiting for initial photo
- `AWAITING_LOCATION` - Photo received, no GPS data, asking for location
- `AWAITING_PLATE` - Photo received, asking for license plate
- `AWAITING_CONFIRMATION` - Plate validated, asking for confirmation
- `AWAITING_NAME` - Sighting saved, asking for contributor name
