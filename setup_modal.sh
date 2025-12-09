#!/bin/bash
# Setup script for Modal deployment

set -e

echo "🚀 Setting up Modal for Fisker Ocean Bot"
echo ""

# Check if Modal token exists
if ! uv run modal token show &>/dev/null; then
    echo "📝 No Modal token found. Setting up authentication..."
    echo "This will open your browser to authenticate with Modal."
    echo ""
    uv run modal token new
else
    echo "✓ Modal token already configured"
fi

echo ""
echo "🔑 Setting up secrets..."
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found"
    echo "Please create a .env file with your credentials first"
    exit 1
fi

# Source .env file
source .env

# Create Bluesky credentials secret
echo "Creating Bluesky credentials secret..."
uv run modal secret create bluesky-credentials \
    BLUESKY_HANDLE="$BLUESKY_HANDLE" \
    BLUESKY_PASSWORD="$BLUESKY_PASSWORD" \
    --force

echo "✓ Bluesky credentials configured"

# Create Neon database secret
echo "Creating Neon database secret..."
uv run modal secret create neon-db \
    DATABASE_URL="$DATABASE_URL" \
    --force

echo "✓ Neon database configured"

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Test locally:    uv run modal run modal_app.py --command=stats"
echo "  2. Deploy to Modal: uv run modal deploy modal_app.py"
echo "  3. View logs:       uv run modal app logs fisker-ocean-bot"
echo ""
echo "See MODAL_SETUP.md for detailed documentation"
