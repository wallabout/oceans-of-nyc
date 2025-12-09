# Quick Start: Modal Deployment

## 🚀 Deploy in 3 Steps

### Step 1: Setup
```bash
./setup_modal.sh
```

### Step 2: Test
```bash
uv run modal run modal_app.py --command=stats
```

### Step 3: Deploy
```bash
uv run modal deploy modal_app.py
```

That's it! Your bot will now run automatically every 6 hours. 🎉

---

## 📋 Common Commands

### Development
```bash
# Get database statistics
uv run modal run modal_app.py --command=stats

# Dry run (test without posting)
uv run modal run modal_app.py --command=post --dry-run=true

# Post 3 sightings (for real)
uv run modal run modal_app.py --command=post --limit=3
```

### Production
```bash
# Deploy/update the app
uv run modal deploy modal_app.py

# View live logs
uv run modal app logs fisker-ocean-bot --follow

# View recent logs
uv run modal app logs fisker-ocean-bot

# Stop scheduled runs
uv run modal app stop fisker-ocean-bot

# List all apps
uv run modal app list
```

---

## 🔧 Troubleshooting

### "Secret not found"
```bash
# List secrets
uv run modal secret list

# Re-run setup
./setup_modal.sh
```

### "Connection error"
```bash
# Test Neon connection locally
uv run python -c "from database import SightingsDatabase; db = SightingsDatabase(); print('✓ Connected')"
```

### Check deployment status
```bash
uv run modal app show fisker-ocean-bot
```

---

## 📊 What's Running?

Once deployed:
- ⏰ **Schedule**: Every 6 hours
- 📝 **Posts per run**: Up to 3 sightings
- 💰 **Cost**: $0 (free tier)
- 🌍 **Location**: Cloud (Modal)

---

## 📖 More Info

- Full setup guide: [MODAL_SETUP.md](MODAL_SETUP.md)
- Architecture: [DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md)
- General docs: [README.md](README.md)
