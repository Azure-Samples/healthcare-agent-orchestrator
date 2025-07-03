#!/bin/bash
# Build script for the React frontend

set -e # Exit on error

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DEMOCLIENT_DIR="$PROJECT_ROOT/democlient"
SRC_DIR="$DEMOCLIENT_DIR/src"
BUILD_DIR="$DEMOCLIENT_DIR/build"
STATIC_DIR="$PROJECT_ROOT/src/static"

# Get environment values
echo "Getting environment variables from azd..."
eval "$(azd env get-values)"

# Check if frontend build is disabled
if [ "$DISABLE_FRONT_END" = "true" ]; then
    echo "Frontend build is disabled (DISABLE_FRONT_END=true). Skipping frontend build."
    exit 0
fi

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "Node.js is required for frontend build but not installed."
    exit 1
fi

# Check if npm is installed
if ! command -v npm &> /dev/null; then
    echo "npm is required for frontend build but not installed."
    exit 1
fi

# Navigate to the React project directory
cd "$DEMOCLIENT_DIR"

echo "Installing frontend dependencies..."
npm install

# Create .env.production file with Vite environment variables
echo "Creating .env.production with environment variables..."
cat > .env.production <<EOF
VITE_API_BASE_URL=${REACT_APP_API_BASE_URL:-}
EOF

echo "Building React frontend..."
npm run build

# Check if build was successful
if [ ! -d "$BUILD_DIR" ]; then
    echo "Error: Build directory does not exist. Frontend build may have failed."
    exit 1
fi

echo "Copying build files to src/static/static directory for deployment..."

# Create the static directory structure that the Python app expects
mkdir -p "$STATIC_DIR/static"

# Remove existing files in the target directory
rm -rf "$STATIC_DIR/static"/*

# Copy all build files to the static/static directory (note the double static)
cp -R "$BUILD_DIR"/* "$STATIC_DIR/static"/

echo "Frontend build completed successfully!"
echo "Files copied to: $STATIC_DIR/static"
echo "Build contents:"
ls -la "$STATIC_DIR/static" 